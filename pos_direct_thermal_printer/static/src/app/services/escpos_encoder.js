/** @odoo-module */

import { DTRP_DEFAULTS } from "@pos_direct_thermal_printer/app/constants";

const ESC = 0x1b;
const GS = 0x1d;

function bytes(...values) {
    return values;
}

function asciiSafe(text) {
    return String(text || "")
        .normalize("NFKD")
        .replace(/[^\x20-\x7E\r\n]/g, "");
}

function textBytes(text) {
    return Array.from(new TextEncoder().encode(asciiSafe(text)));
}

function splitText(text, width) {
    const source = asciiSafe(text);
    const result = [];
    for (const rawLine of source.split(/\r?\n/)) {
        let line = rawLine;
        while (line.length > width) {
            let cut = line.lastIndexOf(" ", width);
            if (cut <= 0) {
                cut = width;
            }
            result.push(line.slice(0, cut));
            line = line.slice(cut).trimStart();
        }
        result.push(line);
    }
    return result;
}

function fit(text, width) {
    const safe = asciiSafe(text);
    return safe.length > width ? safe.slice(0, width) : safe;
}

function twoColumn(left, right, width) {
    const safeRight = asciiSafe(right);
    const rightWidth = Math.min(safeRight.length, Math.floor(width / 2));
    const leftWidth = width - rightWidth - 1;
    return `${fit(left, leftWidth).padEnd(leftWidth, " ")} ${safeRight.slice(0, rightWidth).padStart(rightWidth, " ")}`;
}

function line(char, width) {
    return char.repeat(width);
}

export class DtrpEscposEncoder {
    constructor(config) {
        this.config = config || {};
        this.width = DTRP_DEFAULTS.paperColumns[this.config.dtrp_paper_width] || 48;
        this.output = [];
    }

    push(values) {
        this.output.push(...values);
    }

    command(...values) {
        this.push(bytes(...values));
    }

    text(value = "") {
        this.push(textBytes(value));
    }

    nl(count = 1) {
        this.text("\n".repeat(count));
    }

    align(mode = "left") {
        const value = mode === "center" ? 1 : mode === "right" ? 2 : 0;
        this.command(ESC, 0x61, value);
    }

    bold(enabled) {
        this.command(ESC, 0x45, enabled ? 1 : 0);
    }

    size(doubleWidth = false, doubleHeight = false) {
        const value = (doubleWidth ? 0x20 : 0x00) + (doubleHeight ? 0x10 : 0x00);
        this.command(GS, 0x21, value);
    }

    writeLine(value = "", options = {}) {
        this.align(options.align || "left");
        this.bold(Boolean(options.bold));
        this.size(Boolean(options.doubleWidth), Boolean(options.doubleHeight));
        for (const part of splitText(value, this.width)) {
            this.text(part);
            this.nl();
        }
        this.bold(false);
        this.size(false, false);
        this.align("left");
    }

    separator(char = "-") {
        this.writeLine(line(char, this.width));
    }

    moneyLine(label, amount, options = {}) {
        this.writeLine(twoColumn(label, amount, this.width), options);
    }

    productLine(lineData) {
        this.writeLine(lineData.name || "Item");
        const qty = [lineData.qty, lineData.unit].filter(Boolean).join(" ");
        const left = qty ? `${qty} x ${lineData.unitPrice || ""}` : lineData.unitPrice || "";
        this.writeLine(twoColumn(left, lineData.price || "", this.width));
        if (lineData.discount && Number(lineData.discount) > 0) {
            this.writeLine(`Discount: ${lineData.discount}%`);
        }
        if (lineData.customerNote) {
            this.writeLine(`Note: ${lineData.customerNote}`);
        }
    }

    openDrawer() {
        this.command(ESC, 0x70, 0x00, 0x19, 0xfa);
    }

    cut() {
        this.command(GS, 0x56, 0x00);
    }

    encode(receipt) {
        this.command(ESC, 0x40);
        this.command(ESC, 0x74, 0x00);
        if (this.config.dtrp_open_cash_drawer) {
            this.openDrawer();
        }
        this.writeHeader(receipt);
        this.separator();
        for (const lineData of receipt.lines) {
            this.productLine(lineData);
        }
        this.separator();
        this.moneyLine("Subtotal", receipt.totalWithoutTax);
        this.moneyLine("Tax", receipt.tax);
        if (receipt.showDiscountTotal) {
            this.moneyLine("Discount", receipt.discount);
        }
        this.moneyLine("TOTAL", receipt.total, { bold: true });
        const paymentDisplayLines = receipt.paymentDisplayLines || receipt.paymentLines || [];
        if (paymentDisplayLines.length) {
            this.separator();
            for (const payment of paymentDisplayLines) {
                this.moneyLine(payment.name || "Payment", payment.amount);
            }
        }
        if (receipt.showChange) {
            this.moneyLine("CHANGE", receipt.change, { bold: true });
        }
        this.writeFooter(receipt);
        this.nl(receipt.bottomFeedLines ?? this.config.dtrp_bottom_feed_lines ?? 6);
        if (this.config.dtrp_cut_paper) {
            this.cut();
        }
        return new Uint8Array(this.output);
    }

    writeHeader(receipt) {
        const metadataLines = receipt.metadataLines || [];
        if (metadataLines.length) {
            metadataLines.forEach((value, index) => {
                this.writeLine(value, {
                    align: "center",
                    bold: index === 0,
                    doubleHeight: index === 0 && this.config.dtrp_paper_width === "80",
                });
            });
        } else {
            this.writeLine("Receipt", {
                align: "center",
                bold: true,
                doubleHeight: this.config.dtrp_paper_width === "80",
            });
        }
        if (receipt.header) {
            this.nl();
            this.writeLine(receipt.header, { align: "center" });
        }
        this.nl();
        this.writeLine(twoColumn("Receipt", receipt.orderName, this.width));
        this.writeLine(twoColumn("Date", receipt.date, this.width));
        if (receipt.cashier) {
            this.writeLine(twoColumn("Cashier", receipt.cashier, this.width));
        }
        if (receipt.customer) {
            this.writeLine(twoColumn("Customer", receipt.customer, this.width));
        }
    }

    writeFooter(receipt) {
        if (receipt.loyaltyLines?.length) {
            this.separator();
            receipt.loyaltyLines.forEach((value, index) => {
                this.writeLine(value, {
                    align: index === 0 ? "center" : "left",
                    bold: index === 0,
                });
            });
        }
        if (receipt.footer) {
            this.separator();
            this.writeLine(receipt.footer, { align: "center" });
        }
        if (receipt.termsConditions) {
            this.separator();
            this.writeLine(receipt.termsConditions, { align: "center" });
        }
    }
}

export function dtrpEncodeReceipt(receipt, config) {
    return new DtrpEscposEncoder(config).encode(receipt);
}

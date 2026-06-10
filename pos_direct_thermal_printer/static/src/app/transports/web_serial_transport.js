/** @odoo-module */

export async function dtrpPrintViaWebSerial({ config, bytes, logger, pos, order }) {
    if (!("serial" in navigator)) {
        throw new Error("Web Serial is not available in this browser.");
    }
    logger.warn(pos, "requesting Web Serial printer port", {
        printer: config.dtrp_printer_identifier || "",
    }, order);
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: 9600 });
    try {
        const writer = port.writable.getWriter();
        try {
            await writer.write(bytes);
        } finally {
            writer.releaseLock();
        }
    } finally {
        await port.close();
    }
    logger.info(pos, "Web Serial print job written", {
        byteLength: bytes.length,
    }, order);
    return { ok: true };
}

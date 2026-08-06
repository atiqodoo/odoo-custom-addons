/** @odoo-module */

import { DTRP_DEFAULTS } from "@pos_direct_thermal_printer/app/constants";

function normalizeBaseUrl(url) {
    return String(url || "").replace(/\/+$/, "");
}

function bytesToBase64(bytes) {
    let binary = "";
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }
    return btoa(binary);
}

async function fetchWithTimeout(url, options, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

export async function dtrpPrintViaLocalBridge({ config, receipt, bytes, logger, pos, order }) {
    const baseUrl = normalizeBaseUrl(config.dtrp_bridge_url);
    if (!baseUrl) {
        throw new Error("Local bridge URL is empty.");
    }
    const url = `${baseUrl}${DTRP_DEFAULTS.bridgePath}`;
    const headers = {
        "Content-Type": "application/json",
    };
    if (config.dtrp_bridge_token) {
        headers["X-Odoo-Print-Token"] = config.dtrp_bridge_token;
    }
    const payload = {
        job_id: `${receipt.orderUid || Date.now()}`,
        printer: config.dtrp_printer_identifier || "",
        profile: config.dtrp_receipt_profile,
        paper_width: config.dtrp_paper_width,
        encoding: "base64",
        payload_base64: bytesToBase64(bytes),
        receipt_summary: {
            order: receipt.orderName,
            cashier: receipt.cashier,
            line_count: receipt.lines.length,
            payment_count: receipt.paymentLines.length,
            amount_total: receipt.raw.amountTotal,
        },
    };
    logger.debug(pos, "posting print job to local bridge", {
        url,
        printer: payload.printer,
        job_id: payload.job_id,
        byteLength: bytes.length,
    }, order);
    const response = await fetchWithTimeout(
        url,
        {
            method: "POST",
            headers,
            body: JSON.stringify(payload),
            mode: "cors",
        },
        config.dtrp_timeout_ms || 8000
    );
    const responseText = await response.text();
    let responseJson = null;
    try {
        responseJson = responseText ? JSON.parse(responseText) : null;
    } catch {
        responseJson = null;
    }
    if (!response.ok) {
        throw new Error(`Local bridge returned HTTP ${response.status}: ${responseText}`);
    }
    if (responseJson && responseJson.ok === false) {
        throw new Error(responseJson.message || "Local bridge rejected print job.");
    }
    logger.info(pos, "local bridge accepted print job", {
        status: response.status,
        response: responseJson || responseText,
    }, order);
    return { ok: true, response: responseJson || responseText };
}

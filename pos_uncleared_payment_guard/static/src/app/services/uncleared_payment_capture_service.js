/** @odoo-module */

import { upgLogger } from "@pos_uncleared_payment_guard/app/logger";

export function upgGetDepositBankJournals(pos) {
    const journals = pos?.models?.["account.journal"]?.getAll?.() || [];
    const bankJournals = journals.filter((journal) => journal.type === "bank");
    upgLogger.warn(pos, "deposit bank journals available", {
        count: bankJournals.length,
        journals: bankJournals.map((journal) => ({
            id: journal.id,
            name: journal.name,
            code: journal.code,
        })),
    });
    return bankJournals;
}

export function upgApplyCaptureToPaymentLine(pos, paymentLine, capture) {
    const journal = capture.depositBankJournal;
    const vals = {
        upg_deposit_bank_journal_id: journal,
        upg_cheque_bank: (capture.chequeBank || "").trim(),
        upg_cheque_account_number: (capture.chequeAccountNumber || "").trim(),
        upg_cheque_number: (capture.chequeNumber || "").trim(),
        upg_cheque_date: capture.chequeDate || false,
    };
    if (paymentLine?.update) {
        paymentLine.update(vals);
    } else {
        Object.assign(paymentLine, vals);
    }
    upgLogger.warn(pos, "capture metadata applied to payment line", {
        paymentLineUuid: paymentLine?.uuid,
        method: paymentLine?.payment_method_id?.name,
        amount: paymentLine?.amount,
        depositBankJournalId: journal?.id,
        depositBankJournalName: journal?.name,
        chequeBank: vals.upg_cheque_bank,
        chequeAccountNumber: vals.upg_cheque_account_number,
        chequeNumber: vals.upg_cheque_number,
        chequeDate: vals.upg_cheque_date,
    });
}

export function upgPaymentLineHasCapture(paymentLine) {
    return Boolean(
        paymentLine?.upg_deposit_bank_journal_id &&
        paymentLine?.upg_cheque_bank &&
        paymentLine?.upg_cheque_account_number &&
        paymentLine?.upg_cheque_number &&
        paymentLine?.upg_cheque_date
    );
}

"""BeeForce Payouts & Billing module selectors."""


class PayoutsPage:
    GENERATE_INVOICE = '[data-testid="generate-invoice-btn"]'
    INVOICE_TABLE = '[data-testid="invoice-list"]'
    WAGE_SUMMARY = '[data-testid="wage-summary"]'
    PF_ESI_SECTION = '[data-testid="pf-esi"]'
    DOWNLOAD_INVOICE = '[aria-label="Download invoice"]'
    PAYMENT_STATUS = '[data-testid="payment-status"]'
    BILLING_PERIOD = '[aria-label="Select billing period"]'

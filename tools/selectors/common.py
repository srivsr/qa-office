"""BeeForce common selectors — login, navigation, shared elements."""


class LoginPage:
    EMAIL = '[data-testid="email-input"]'
    PASSWORD = '[data-testid="password-input"]'
    SUBMIT = 'button[type="submit"]'
    ERROR = '[data-testid="login-error"]'


class NavBar:
    ATTENDANCE = '[aria-label="Attendance"]'
    PAYOUTS = '[aria-label="Payouts & Billing"]'
    ONBOARDING = '[aria-label="Onboarding"]'
    COMPLIANCE = '[aria-label="Compliance"]'
    ENGAGEMENT = '[aria-label="Workforce Engagement"]'
    OFFBOARDING = '[aria-label="Offboarding"]'


class Toast:
    SUCCESS = '[data-testid="toast-success"]'
    ERROR = '[data-testid="toast-error"]'

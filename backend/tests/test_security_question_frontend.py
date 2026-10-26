"""Static frontend contracts for security-question recovery navigation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend"


def test_login_links_to_recovery():
    html = (ROOT / "login.html").read_text()
    assert 'href="forgot-password.html" id="forgot"' in html
    assert 'Password reset isn\'t set up yet' not in html


def test_recovery_has_all_three_steps():
    html = (ROOT / "forgot-password.html").read_text()
    for marker in ('id="lookup"', 'id="verify" hidden', 'id="reset" hidden',
                   'id="username"', 'id="newPw"', 'id="confirmPw"',
                   '/api/security-questions/'):
        assert marker in html


def test_question_setup_links_are_valid():
    html = (ROOT / "security-questions.html").read_text()
    for path in ("driver/profile.html", "sponsor/drivers.html", "admin/users.html"):
        assert (ROOT / path).is_file()
        assert path in html
    profile = (ROOT / "driver/profile.html").read_text()
    assert 'href="../security-questions.html"' in profile


def test_recovery_uses_existing_login_layout_and_css():
    for page in ("forgot-password.html", "security-questions.html"):
        html = (ROOT / page).read_text()
        for marker in ('class="auth"', 'class="auth-side"', 'class="auth-main"',
                       'class="auth-card"', 'assets/css/app.css', 'assets/img/logo.png',
                       'class="btn go"'):
            assert marker in html
    css = (ROOT / "assets/css/app.css").read_text()
    assert "[hidden]{display:none!important}" in css

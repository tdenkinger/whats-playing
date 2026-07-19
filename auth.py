import hashlib
import hmac
import os

import streamlit as st
import streamlit.components.v1 as components

COOKIE_NAME = "wp_auth"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def _auth_token(password: str) -> str:
    # Derived from the password so a token can't be produced without knowing it.
    return hmac.new(password.encode(), b"whats-playing-auth", hashlib.sha256).hexdigest()


def _set_cookie(value: str) -> None:
    components.html(
        f"""<script>
document.cookie = "{COOKIE_NAME}={value}; path=/; max-age={COOKIE_MAX_AGE}; SameSite=Lax";
</script>""",
        height=0,
    )


def _clear_cookie() -> None:
    components.html(
        f"""<script>
document.cookie = "{COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
</script>""",
        height=0,
    )


def require_password() -> None:
    """Gate the current page behind a shared site password.

    No-op if SITE_PASSWORD isn't set, so local development stays open.
    Login is remembered for a year via a browser cookie (session_state
    alone doesn't survive a full browser reload). Streamlit has no
    server-side cookie API, so the cookie is set/cleared via a small
    injected script.
    Must be called right after st.set_page_config().
    """
    password = os.environ.get("SITE_PASSWORD")
    if not password:
        return

    expected_token = _auth_token(password)
    if st.session_state.get("authenticated") or st.context.cookies.get(COOKIE_NAME) == expected_token:
        st.session_state["authenticated"] = True
        return

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.title("🔒 What's Playing")
        with st.form("password_form"):
            entered = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Enter")

        if submitted:
            if hmac.compare_digest(entered, password):
                st.session_state["authenticated"] = True
                _set_cookie(expected_token)
                st.rerun()
            else:
                st.error("Incorrect password.")

    st.stop()


def logout_button() -> None:
    """Render a sidebar logout control if the password gate is active."""
    if not os.environ.get("SITE_PASSWORD"):
        return
    if st.sidebar.button("Log out"):
        st.session_state["authenticated"] = False
        _clear_cookie()
        st.rerun()

import hmac
import os

import streamlit as st


def require_password() -> None:
    """Gate the current page behind a shared site password.

    No-op if SITE_PASSWORD isn't set, so local development stays open.
    Must be called right after st.set_page_config().
    """
    password = os.environ.get("SITE_PASSWORD")
    if not password or st.session_state.get("authenticated"):
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
        st.rerun()

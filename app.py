import streamlit as st

# Configure the app’s appearance and title
st.set_page_config(page_title="Pitch Tracker")

# Create a friendly redirect notice
st.title("Pitch Tracker")
st.info("Please open the **Game Setup** page in the sidebar first to start a new game.")
st.markdown("Once a game is started, you can switch to the **Tracker** page to record pitches.")


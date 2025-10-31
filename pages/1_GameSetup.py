import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Game Setup")

# -----------------------------
# Supabase connection
# -----------------------------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------
# Helper functions
# -----------------------------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name; create if missing."""
    if not name.strip():
        return None
    r = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if r.data:
        return r.data[0]["PlayerID"]
    payload = {"Name": name}
    if team:
        payload["Team"] = team
    if throws:
        payload["Throws"] = throws
    if bats:
        payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    return created.data[0]["PlayerID"] if created.data else None


def create_game(home, away, gamedate):
    resp = supabase.table("Games").insert({
        "HomeTeam": home,
        "AwayTeam": away,
        "GameDate": str(gamedate)
    }).execute()
    return resp.data[0]["GameID"] if resp.data else None


# -----------------------------
# Initialize session defaults
# -----------------------------
for key, default in {
    "lineup": [],
    "pitchers": [],
    "selected_game_id": None,
    "game_active": False
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# -----------------------------
# 1 — Game Setup & Lineup
# -----------------------------
st.title("Game Setup")
st.caption("Create a new game, manage lineup, and add pitchers.")

with st.expander("1 — Game Setup & Lineup", expanded=True):
    col1, col2, col3 = st.columns([3, 3, 2])

    # ----------- Game Select/Create -----------
    with col1:
        games = supabase.table("Games").select(
            "GameID, GameDate, HomeTeam, AwayTeam"
        ).order("GameDate", desc=True).execute().data or []
        game_map = {
            f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"]
            for g in games
        }

        sel_game = st.selectbox(
            "Select Game",
            ["-- Add New Game --"] + list(game_map.keys())
        )

        if sel_game == "-- Add New Game --":
            home = st.text_input("Home Team")
            away = st.text_input("Away Team")
            gamedate = st.date_input("Game Date", value=date.today())
            if st.button("Create Game"):
                gid = create_game(home, away, gamedate)
                if gid:
                    st.success("Game created. Re-open select to pick it.")
                    st.experimental_rerun()
                else:
                    st.error("Failed to create game.")
            st.stop()
        else:
            st.session_state["selected_game_id"] = game_map[sel_game]
            st.info(f"Selected Game: {sel_game}")

    # ----------- Lineup (Hitters) -----------
    existing_players = supabase.table("Players").select("Name").execute().data or []
    all_names = [p["Name"] for p in existing_players]

    with col2:
        st.subheader("Lineup")

        # single set of input widgets with session keys
        hname = st.text_input("Hitter name", key="hname")
        hbats = st.selectbox("Bats", ["Right", "Left", "Switch"], key="hbats")

        if hname:
            matches = [n for n in all_names if hname.lower() in n.lower()]
            if matches:
                st.caption("Existing players: " + ", ".join(matches[:5]))

        if st.button("Add Hitter"):
            if not hname:
                st.warning("Enter a name.")
            elif any(
                p["Name"].lower() == hname.lower()
                for p in st.session_state["lineup"]
            ):
                st.error("⚠️ Batter already in lineup.")
            else:
                pid = ensure_player(hname, bats=hbats)
                order = len(st.session_state["lineup"]) + 1
                st.session_state["lineup"].append({
                    "Name": hname,
                    "Bats": hbats,
                    "Order": order,
                    "PlayerID": pid
                })
                st.success(f"Added {hname} as #{order}")
                # reset fields
                st.session_state["hname"] = ""
                st.session_state["hbats"] = "Right"
                st.experimental_rerun()

        # Display lineup list
        for i, p in enumerate(st.session_state["lineup"]):
            c1, c2 = st.columns([6, 1])
            c1.write(f"{p['Order']}. {p['Name']} ({p['Bats']})")
            if c2.button("❌", key=f"delh{i}"):
                st.session_state["lineup"].pop(i)
                st.experimental_rerun()

    # ----------- Pitchers -----------
    with col3:
        st.subheader("Pitchers")

        pname = st.text_input("Pitcher name", key="pname")
        pthrows = st.selectbox("Throws", ["Right", "Left"], key="pthrows")

        if pname:
            matches = [n for n in all_names if pname.lower() in n.lower()]
            if matches:
                st.caption("Existing players: " + ", ".join(matches[:5]))

        if st.button("Add Pitcher"):
            if not pname:
                st.warning("Enter pitcher name.")
            elif any(
                p["Name"].lower() == pname.lower()
                for p in st.session_state["pitchers"]
            ):
                st.error("⚠️ Pitcher already added.")
            else:
                pid = ensure_player(pname, throws=pthrows)
                st.session_state["pitchers"].append({
                    "Name": pname,
                    "Throws": pthrows,
                    "PlayerID": pid
                })
                st.success(f"Added pitcher {pname}")
                # reset fields
                st.session_state["pname"] = ""
                st.session_state["pthrows"] = "Right"
                st.experimental_rerun()

        # Display pitcher list
        for j, q in enumerate(st.session_state["pitchers"]):
            c1, c2 = st.columns([6, 1])
            c1.write(f"{q['Name']} ({q['Throws']})")
            if c2.button("❌", key=f"delp{j}"):
                st.session_state["pitchers"].pop(j)
                st.experimental_rerun()


# -----------------------------
# 2 — Start Game Button
# -----------------------------
st.markdown("---")
if st.session_state["selected_game_id"]:
    if st.button("🚀 Start Game"):
        st.session_state["game_active"] = True
        st.success("Game started — switching to Tracker!")
        st.switch_page("pages/2_Tracker.py")
else:
    st.info("Select or create a game first.")

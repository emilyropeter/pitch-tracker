# app.py
import streamlit as st
from supabase import create_client
from datetime import date
import os

# ---------- Supabase setup ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials not found. Please set them in Streamlit Secrets.")
    st.stop()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Baseball Game Tracker", layout="wide")
st.title("⚾ Baseball Game Tracker")

# ---------- utility functions ----------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name, creating if necessary."""
    if not name:
        return None
    res = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    rows = res.data
    if rows:
        return rows[0]["PlayerID"]
    # create
    payload = {"Name": name}
    if team:
        payload["Team"] = team
    if throws:
        payload["Throws"] = throws
    if bats:
        payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    if created.data:
        return created.data[0]["PlayerID"]
    return None

def create_atbat(game_id, batter_id, pitcher_id, inning, leadoff=None, leadoff_on=None, play_result=None, runs_scored=0, earned_runs=0, korbb=None):
    payload = {
        "GameID": game_id,
        "BatterID": batter_id,
        "PitcherID": pitcher_id,
        "Inning": inning,
        "RunsScored": runs_scored,
        "EarnedRuns": earned_runs
    }
    # optional fields only include if set
    if leadoff is not None:
        payload["LeadOff"] = leadoff
    if leadoff_on is not None:
        payload["LeadOffOn"] = leadoff_on
    if play_result:
        payload["PlayResult"] = play_result
    if korbb:
        payload["KorBB"] = korbb
    res = supabase.table("AtBats").insert(payload).execute()
    return res.data[0]["AtBatID"] if res.data else None

def next_pitch_numbers(pitcher_id, atbat_id):
    # PitchNo = 1 + max PitchNo for that pitcher across DB (global)
    all_by_pitcher = supabase.table("Pitches").select("PitchNo").eq("PitcherID", pitcher_id).order("PitchID", desc=True).limit(1).execute().data
    if all_by_pitcher:
        global_next = all_by_pitcher[0].get("PitchNo", 0) + 1
    else:
        global_next = 1
    # PitchOfAB = count pitches with this AtBatID + 1
    ab_pitches = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).execute().data
    local_next = len(ab_pitches) + 1
    return global_next, local_next

def compute_wel(balls, strikes):
    # "Win if count is 0-2 or 1-2, Lose if 2-0 or 2-1 and Early if 0-0,0-1,1-0,1-1"
    if balls == 0 and strikes == 0: return "E"
    if balls == 0 and strikes == 1: return "E"
    if balls == 1 and strikes == 0: return "E"
    if balls == 1 and strikes == 1: return "E"
    if balls == 0 and strikes == 2: return "W"
    if balls == 1 and strikes == 2: return "W"
    if balls == 2 and strikes == 0: return "L"
    if balls == 2 and strikes == 1: return "L"
    # default None
    return None

def get_lineup_from_db(game_id):
    """Optionally load lineup saved for a game (not implemented in DB schema)."""
    # placeholder — we keep lineup in session by default
    return []

def delete_pitch(pitch_id):
    supabase.table("Pitches").delete().eq("PitchID", pitch_id).execute()

# ---------- session state defaults ----------
if "lineup" not in st.session_state:
    st.session_state["lineup"] = []  # list of dicts: {"Name","Team","Bats","Order"}
if "pitchers" not in st.session_state:
    st.session_state["pitchers"] = []  # list of dicts {"Name","Team","Throws"}
if "current_atbat_id" not in st.session_state:
    st.session_state["current_atbat_id"] = None
if "balls" not in st.session_state:
    st.session_state["balls"] = 0
if "strikes" not in st.session_state:
    st.session_state["strikes"] = 0
if "pitch_history" not in st.session_state:
    st.session_state["pitch_history"] = []  # stack of pitchIDs
if "last_pitch_summary" not in st.session_state:
    st.session_state["last_pitch_summary"] = None

# ---------- 1) Game selection & lineup setup ----------
with st.expander("1 — Game Selection & Lineup Setup", expanded=True):
    # load games
    games = supabase.table("Games").select("*").order("GameDate", desc=True).execute().data or []
    game_options = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}
    selected_game = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_options.keys()))

    if selected_game == "-- Add New Game --":
        st.subheader("Add a New Game")
        home_team = st.text_input("Home Team")
        away_team = st.text_input("Away Team")
        game_date = st.date_input("Game Date", date.today())
        if st.button("Save Game"):
            res = supabase.table("Games").insert({
                "HomeTeam": home_team,
                "AwayTeam": away_team,
                "GameDate": str(game_date)
            }).execute()
            if res.data:
                st.success("Game saved. Please re-select it from the dropdown.")
                st.experimental_rerun()
            else:
                st.error("Failed to save game.")
        st.stop()
    else:
        game_id = game_options[selected_game]
        st.success(f"Selected game: {selected_game}")

    # Lineup setup UI
    st.markdown("**Lineup setup — add starting 9 (or subs).**\nYou can add hitters here so they're available quickly during the game.")
    col1, col2, col3 = st.columns([3,2,1])
    with col1:
        new_hitter_name = st.text_input("New Hitter Name")
    with col2:
        new_hitter_side = st.selectbox("Bats", ["Right", "Left", "Switch"], key="new_hitter_bats")
    with col3:
        new_hitter_slot = st.number_input("Lineup Position (1-9)", min_value=1, max_value=99, step=1, value=len(st.session_state["lineup"])+1)
    add_hitter = st.button("Add Hitter")
    if add_hitter:
        if new_hitter_name:
            # add to DB and session
            pid = ensure_player(new_hitter_name, team=None, bats=new_hitter_side)
            st.session_state["lineup"].append({"Name": new_hitter_name, "Team": None, "Bats": new_hitter_side, "Order": int(new_hitter_slot)})
            # sort lineup by Order
            st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
            st.success(f"Added hitter {new_hitter_name} to lineup.")
        else:
            st.warning("Enter hitter name first.")

    # show lineup table with ability to remove or edit
    if st.session_state["lineup"]:
        st.markdown("**Current lineup:**")
        for i, hitter in enumerate(st.session_state["lineup"]):
            cols = st.columns([4,2,1,1])
            cols[0].write(f"{hitter['Order']}. {hitter['Name']} ({hitter['Bats']})")
            if cols[3].button(f"Remove-{i}"):
                st.session_state["lineup"].pop(i)
                st.experimental_rerun()

    # Pitcher setup
    st.markdown("---")
    st.markdown("**Pitchers (add starters/relievers here)**")
    pcol1, pcol2 = st.columns([3,1])
    with pcol1:
        new_pitcher_name = st.text_input("New Pitcher Name", key="new_pitcher_name")
    with pcol2:
        new_pitcher_throws = st.selectbox("Throws", ["Right", "Left"], key="new_pitcher_throws")
    add_pitcher_btn = st.button("Add Pitcher")
    if add_pitcher_btn:
        if new_pitcher_name:
            pid = ensure_player(new_pitcher_name, team=None, throws=new_pitcher_throws)
            st.session_state["pitchers"].append({"Name": new_pitcher_name, "Throws": new_pitcher_throws})
            st.success(f"Added pitcher {new_pitcher_name}.")
        else:
            st.warning("Enter pitcher name first.")

# ---------- 2) AtBat selection / Add Batter ----------
st.header("2 — AtBat Selection")
colA, colB = st.columns([2,1])
with colA:
    # Populate batter dropdown from lineup
    lineup_names = [p["Name"] for p in st.session_state["lineup"]]
    atbat_choice = st.selectbox("Select Batter (or choose Add Batter)", ["-- Select Batter --", "-- Add Batter --"] + lineup_names)
    # If Add Batter chosen, show add batter form (place in lineup)
    if atbat_choice == "-- Add Batter --":
        st.subheader("Add Batter (to lineup & create AtBat)")
        add_name = st.text_input("Batter Name (new)")
        add_bats = st.selectbox("Bats", ["Right", "Left", "Switch"], key="addbats")
        add_pos = st.number_input("Lineup Position", min_value=1, max_value=99, value=len(st.session_state["lineup"])+1)
        add_team_choice = st.selectbox("Batter Team", ["Home", "Away", "Unknown"])
        if st.button("Add Batter & Start AtBat"):
            # add player and lineup
            pid = ensure_player(add_name, team=None, bats=add_bats)
            st.session_state["lineup"].append({"Name": add_name, "Team": None, "Bats": add_bats, "Order": int(add_pos)})
            st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
            # create AtBat immediately: need pitcher selected (choose current pitcher)
            st.success("Batter added. Now select pitcher below to start at-bat.")
            st.experimental_rerun()
    elif atbat_choice not in ["-- Select Batter --", "-- Add Batter --"]:
        selected_batter_name = atbat_choice
        st.write(f"Selected batter: {selected_batter_name}")
        # when selecting a batter, create AtBat when coach picks pitcher or clicks "Start AtBat"
with colB:
    # Pitcher selection - show known pitchers
    pitcher_names = [p["Name"] for p in st.session_state["pitchers"]]
    pitcher_select = st.selectbox("Select Pitcher (or Add Pitcher)", ["-- Select Pitcher --", "-- Add Pitcher --"] + pitcher_names)
    if pitcher_select == "-- Add Pitcher --":
        new_p_name = st.text_input("Pitcher Name (new)", key="newpitchname")
        new_p_throws = st.selectbox("Throws", ["Right", "Left"], key="newpitchthrows")
        if st.button("Add Pitcher & Use"):
            pid = ensure_player(new_p_name, team=None, throws=new_p_throws)
            st.session_state["pitchers"].append({"Name": new_p_name, "Throws": new_p_throws})
            st.experimental_rerun()
    elif pitcher_select not in ["-- Select Pitcher --", "-- Add Pitcher --"]:
        selected_pitcher_name = pitcher_select
        st.write(f"Selected pitcher: {selected_pitcher_name}")

# Start AtBat button (creates AtBat record with selected batter and pitcher)
if (atbat_choice not in ["-- Select Batter --", "-- Add Batter --"]) and (pitcher_select not in ["-- Select Pitcher --", "-- Add Pitcher --"]):
    # fetch ids
    batter_pid = ensure_player(atbat_choice)
    pitcher_pid = ensure_player(pitcher_select)
    inning_val = st.number_input("Inning", min_value=1, step=1, value=1)
    if st.button("Start AtBat (create AtBat)"):
        # create AtBat with inferred batter order = lineup position
        order = next((p["Order"] for p in st.session_state["lineup"] if p["Name"] == atbat_choice), None)
        atbat_id = create_atbat(game_id, batter_pid, pitcher_pid, inning=inning_val)
        if atbat_id:
            st.session_state["current_atbat_id"] = atbat_id
            st.session_state["balls"] = 0
            st.session_state["strikes"] = 0
            st.session_state["pitch_history"] = []
            st.session_state["last_pitch_summary"] = None
            st.success(f"AtBat {atbat_id} started for {atbat_choice}.")
            st.experimental_rerun()

# ---------- 3) Pitch Entry ----------
st.header("3 — Pitch Entry (real-time)")

if st.session_state.get("current_atbat_id"):
    atbat_id = st.session_state["current_atbat_id"]

    # load atbat info for display
    ab_row = supabase.table("AtBats").select("*").eq("AtBatID", atbat_id).execute().data[0]
    pitcher_id = ab_row["PitcherID"]
    batter_id = ab_row["BatterID"]
    batter_info = supabase.table("Players").select("Name,Bats").eq("PlayerID", batter_id).execute().data[0]
    pitcher_info = supabase.table("Players").select("Name,Throws").eq("PlayerID", pitcher_id).execute().data[0]

    st.markdown(f"**AtBat {atbat_id} — Batter:** {batter_info['Name']} ({batter_info.get('Bats')})  — **Pitcher:** {pitcher_info['Name']} ({pitcher_info.get('Throws')})")

    # show last pitch summary and Undo button
    if st.session_state["last_pitch_summary"]:
        st.info("Last pitch: " + st.session_state["last_pitch_summary"])
        if st.button("Undo Last Pitch"):
            if st.session_state["pitch_history"]:
                last_id = st.session_state["pitch_history"].pop()
                try:
                    delete_pitch(last_id)
                    # recompute balls/strikes from DB for this atbat
                    remaining = supabase.table("Pitches").select("Balls,Strikes").eq("AtBatID", atbat_id).execute().data or []
                    if remaining:
                        st.session_state["balls"] = remaining[-1].get("Balls", 0)
                        st.session_state["strikes"] = remaining[-1].get("Strikes", 0)
                    else:
                        st.session_state["balls"] = 0
                        st.session_state["strikes"] = 0
                    st.success("Last pitch undone.")
                    st.session_state["last_pitch_summary"] = None
                    st.experimental_rerun()
                except Exception as e:
                    st.error("Failed to undo: " + str(e))
            else:
                st.warning("No pitch to undo.")

    # determine next pitch numbers
    pno, poab = next_pitch_numbers(pitcher_id, atbat_id)
    st.write(f"Next Pitch No: **{pno}** — Pitch of AB: **{poab}**")
    st.write(f"Count: {st.session_state['balls']}-{st.session_state['strikes']}")

    # pitch inputs (quick buttons + optional details)
    st.markdown("**Quick pitch result buttons** (these will auto-update balls/strikes):")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Ball Called"):
            # increment balls
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
            pitch_called = "Ball Called"
            pitch_type = st.selectbox("Pitch Type", ["Fastball", "Changeup", "Curveball", "Slider"], key="pt1")
            velocity = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="vel1")
            # save pitch below using shared code (emulate Save Pitch)
            wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": pitch_type,
                "Velocity": velocity,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": wel_val,
                "Balls": st.session_state["balls"],
                "Strikes": st.session_state["strikes"],
                "TaggedHit": None,
                "HitDirection": None,
                "KPI": None,
                "PitcherID": pitcher_id,
                "BatterID": batter_id
            }).execute()
            if resp.data:
                pid = resp.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_pitch_summary"] = f"{pitch_type} {velocity} — {pitch_called}"
                st.success("Pitch saved.")
                st.experimental_rerun()
    with col2:
        if st.button("Strike Swing Miss"):
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
            pitch_called = "Strike Swing Miss"
            pitch_type = st.selectbox("Pitch Type (swing)", ["Fastball", "Changeup", "Curveball", "Slider"], key="pt2")
            velocity = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="vel2")
            wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": pitch_type,
                "Velocity": velocity,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": wel_val,
                "Balls": st.session_state["balls"],
                "Strikes": st.session_state["strikes"],
                "TaggedHit": None,
                "HitDirection": None,
                "KPI": None,
                "PitcherID": pitcher_id,
                "BatterID": batter_id
            }).execute()
            if resp.data:
                pid = resp.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_pitch_summary"] = f"{pitch_type} {velocity} — {pitch_called}"
                st.success("Pitch saved.")
                st.experimental_rerun()
    with col3:
        if st.button("Foul Ball"):
            # foul counts as strike but not beyond 2
            if st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
            pitch_called = "Foul Ball"
            pitch_type = st.selectbox("Pitch Type (foul)", ["Fastball", "Changeup", "Curveball", "Slider"], key="pt3")
            velocity = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="vel3")
            wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": pitch_type,
                "Velocity": velocity,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": wel_val,
                "Balls": st.session_state["balls"],
                "Strikes": st.session_state["strikes"],
                "TaggedHit": None,
                "HitDirection": None,
                "KPI": None,
                "PitcherID": pitcher_id,
                "BatterID": batter_id
            }).execute()
            if resp.data:
                pid = resp.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_pitch_summary"] = f"{pitch_type} {velocity} — {pitch_called}"
                st.success("Pitch saved.")
                st.experimental_rerun()

    # manual-insert pitch UI for more detail (zone, etc.)
    st.markdown("---")
    st.markdown("**Manual pitch entry (more detail)**")
    with st.form("manual_pitch_form"):
        pitch_type = st.selectbox("Pitch Type", ["Fastball", "Changeup", "Curveball", "Slider"], key="man_pt")
        velocity = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="man_vel")
        zone = st.selectbox("Zone (1-14 or None)", ["None"] + [str(i) for i in range(1,15)], key="man_zone")
        pitch_called = st.selectbox("Pitch Result", ["Ball Called", "Strike Called", "Strike Swing Miss", "Foul Ball", "In Play"], key="man_called")
        tagged = st.selectbox("Tagged Hit", ["None", "Bunt", "Flyball", "Groundball", "Linedrive"], key="man_tag")
        hit_dir = st.selectbox("Hit Direction", ["None", "3-4 Hole", "5-6 Hole", "Catcher", "Center Field",
                                                "First Base", "Left Center", "Left Field", "Middle",
                                                "Pitcher", "Right Center", "Right Field", "Second Base",
                                                "Short Stop", "Third Base"], key="man_hitdir")
        submitted = st.form_submit_button("Save Manual Pitch")

    if submitted:
        # update balls/strikes according to pitch_called
        if pitch_called == "Ball Called":
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
        elif pitch_called in ["Strike Called", "Strike Swing Miss"]:
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
        elif pitch_called == "Foul Ball":
            if st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
        # compute WEL and store
        wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
        zone_val = None if zone == "None" else int(zone)
        tagged_val = None if tagged == "None" else tagged
        hitdir_val = None if hit_dir == "None" else hit_dir

        resp = supabase.table("Pitches").insert({
            "AtBatID": atbat_id,
            "PitchNo": pno,
            "PitchOfAB": poab,
            "PitchType": pitch_type,
            "Velocity": velocity,
            "Zone": zone_val,
            "PitchCalled": pitch_called,
            "WEL": wel_val,
            "Balls": st.session_state["balls"],
            "Strikes": st.session_state["strikes"],
            "TaggedHit": tagged_val,
            "HitDirection": hitdir_val,
            "KPI": None,
            "PitcherID": pitcher_id,
            "BatterID": batter_id
        }).execute()
        if resp.data:
            pid = resp.data[0]["PitchID"]
            st.session_state["pitch_history"].append(pid)
            st.session_state["last_pitch_summary"] = f"{pitch_type} {velocity} — {pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
            st.success("Pitch saved (manual).")
            st.experimental_rerun()
else:
    st.info("Start an AtBat (select batter + pitcher + Start AtBat) before entering pitches.")

# ---------- 4) Runner Events ----------
st.header("4 — Runner Events")
pitch_for_events = st.session_state.get("last_pitch_id", None) or (st.session_state.get("pitch_history")[-1] if st.session_state.get("pitch_history") else None)
# prefer session last_pitch_id, otherwise last item of pitch_history
current_pitch_id = st.session_state.get("last_pitch_id", None)
if not current_pitch_id and st.session_state.get("pitch_history"):
    current_pitch_id = st.session_state["pitch_history"][-1]

if current_pitch_id:
    st.write(f"Logging runner events for Pitch ID: {current_pitch_id}")
    # load players for dropdown
    players = supabase.table("Players").select("PlayerID,Name").execute().data or []
    player_options = {p["Name"]: p["PlayerID"] for p in players}
    selected_runner = st.selectbox("Select Runner", ["-- Select Player --"] + list(player_options.keys()), key="runner_select")
    start_base = st.selectbox("Start Base (1=1st,2=2nd,3=3rd,4=home)", [1,2,3,4], key="start_base")
    end_base = st.selectbox("End Base (1=1st,2=2nd,3=3rd,4=home,0=None)", [1,2,3,4,0], key="end_base", format_func=lambda x: "None" if x==0 else str(x))
    event_type = st.selectbox("Event Type", ["Stolen Base", "Caught Stealing", "Out on Play", "Pickoff", "Advanced on Hit", "Other"], key="evt")
    out_recorded = st.selectbox("Out Recorded", ["No","Yes"], key="outrec")

    if st.button("Save Runner Event"):
        if selected_runner == "-- Select Player --":
            st.warning("Choose a runner first.")
        else:
            runner_id = player_options[selected_runner]
            resp = supabase.table("RunnerEvents").insert({
                "PitchID": current_pitch_id,
                "RunnerID": runner_id,
                "StartBase": start_base,
                "EndBase": None if end_base == 0 else end_base,
                "EventType": event_type,
                "OutRecorded": True if out_recorded == "Yes" else False
            }).execute()
            if resp.data:
                st.success("Runner event saved.")
            else:
                st.error("Failed to save runner event.")
else:
    st.info("Log a pitch first to tie runner events to a pitch.")

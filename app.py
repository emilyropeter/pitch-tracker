# app.py
import streamlit as st
from supabase import create_client
from datetime import date
import os

st.set_page_config(page_title="Baseball Game Tracker", layout="wide")

# -----------------------
# Supabase connection
# -----------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY in env / Streamlit Secrets.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------
# Utilities
# -----------------------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name, creating if necessary."""
    if not name:
        return None
    res = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if res.data:
        return res.data[0]["PlayerID"]
    payload = {"Name": name}
    if team is not None:
        payload["Team"] = team
    if throws is not None:
        payload["Throws"] = throws
    if bats is not None:
        payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    return created.data[0]["PlayerID"] if created.data else None

def create_game(home, away, gamedate):
    resp = supabase.table("Games").insert({"HomeTeam": home, "AwayTeam": away, "GameDate": str(gamedate)}).execute()
    return resp.data[0]["GameID"] if resp.data else None

def create_atbat(game_id, batter_id, pitcher_id, inning, order=None, leadoff=None, leadoff_on=None, play_result=None, runs_scored=0, earned_runs=0, korbb=None):
    payload = {
        "GameID": game_id,
        "BatterID": batter_id,
        "PitcherID": pitcher_id,
        "Inning": inning,
        "RunsScored": runs_scored,
        "EarnedRuns": earned_runs
    }
    if order is not None:
        payload["BatterOrder"] = order
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

def delete_last_pitch(pitch_id):
    supabase.table("Pitches").delete().eq("PitchID", pitch_id).execute()

def next_pitch_numbers_for(atbat_id):
    """Get the next global PitchNo and PitchOfAB safely."""
    # Get next global PitchNo
    res_global = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
    next_pitch_no = res_global.data[0]["PitchNo"] + 1 if res_global.data else 1

    # Get next PitchOfAB for this specific at-bat
    res_ab = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
    next_pitch_of_ab = res_ab.data[0]["PitchOfAB"] + 1 if res_ab.data else 1

    return next_pitch_no, next_pitch_of_ab


def compute_wel(balls, strikes):
    # Early if 0-0,0-1,1-0,1-1 ; Win if 0-2 or 1-2 ; Lose if 2-0 or 2-1
    if (balls, strikes) in [(0,0),(0,1),(1,0),(1,1)]:
        return "E"
    if (balls, strikes) in [(0,2),(1,2)]:
        return "W"
    if (balls, strikes) in [(2,0),(2,1)]:
        return "L"
    return None

# -----------------------
# Session state init
# -----------------------
if "lineup" not in st.session_state:
    st.session_state["lineup"] = []   # list of dicts {Name,Team,Bats,Order}
if "pitchers" not in st.session_state:
    st.session_state["pitchers"] = [] # list of dicts {Name,Throws,Team}
if "selected_game_id" not in st.session_state:
    st.session_state["selected_game_id"] = None
if "current_atbat_id" not in st.session_state:
    st.session_state["current_atbat_id"] = None
if "balls" not in st.session_state:
    st.session_state["balls"] = 0
if "strikes" not in st.session_state:
    st.session_state["strikes"] = 0
if "pitch_history" not in st.session_state:
    st.session_state["pitch_history"] = []  # list of pitchIDs for current atbat, FIFO append
if "last_pitch_summary" not in st.session_state:
    st.session_state["last_pitch_summary"] = None
if "last_saved_pitch_id" not in st.session_state:
    st.session_state["last_saved_pitch_id"] = None

# -----------------------
# Header
# -----------------------
st.title("⚾ Baseball Game Tracker")
st.caption("Set lineup and pitchers in Setup. Use Quick Buttons for realtime pitch entry. Undo last pitch if needed.")

# -----------------------
# 1 — Game selection & lineup setup
# -----------------------
with st.expander("1 — Game Selection & Lineup Setup", expanded=True):
    games = supabase.table("Games").select("*").order("GameDate", desc=True).execute().data or []
    game_map = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}
    selected_game_key = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_map.keys()))
    if selected_game_key == "-- Add New Game --":
        st.subheader("Add New Game")
        home = st.text_input("Home Team")
        away = st.text_input("Away Team")
        gd = st.date_input("Game Date", date.today())
        if st.button("Save Game"):
            gid = create_game(home, away, gd)
            if gid:
                st.success("Game created. Re-open to select it.")
                st.rerun()
            else:
                st.error("Failed to create game.")
        st.stop()
    else:
        st.session_state["selected_game_id"] = game_map[selected_game_key]
        st.success(f"Selected: {selected_game_key}")

    st.markdown("### Lineup (starting hitters & subs)")
    colA, colB, colC = st.columns([3,2,1])
    with colA:
        hitter_name = st.text_input("Hitter Name", key="hitter_name")
    with colB:
        hitter_bats = st.selectbox("Bats", ["Right", "Left", "Switch"], key="hitter_bats")
    with colC:
        hitter_slot = st.number_input("Lineup Slot (1-99)", min_value=1, max_value=99, value=len(st.session_state["lineup"])+1, key="hitter_slot")
    if st.button("Add Hitter"):
        if not hitter_name:
            st.warning("Enter a hitter name.")
        else:
            ensure_player(hitter_name, team=None, bats=hitter_bats)
            st.session_state["lineup"].append({"Name": hitter_name, "Team": None, "Bats": hitter_bats, "Order": int(hitter_slot)})
            st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
            st.success(f"Added hitter {hitter_name}")
            st.rerun()

    if st.session_state["lineup"]:
        st.write("Current lineup:")
        for idx, p in enumerate(st.session_state["lineup"], start=1):
            cols = st.columns([6,1,1])
            cols[0].write(f"{p['Order']}. {p['Name']} ({p['Bats']})")
            if cols[2].button(f"Remove Hitter {idx}"):
                st.session_state["lineup"].pop(idx-1)
                st.success("Removed.")
                st.rerun()

    st.markdown("---")
    st.markdown("### Pitchers (add starters/relievers here)")
    pc1, pc2 = st.columns([4,1])
    with pc1:
        new_pname = st.text_input("Pitcher Name", key="new_pname")
    with pc2:
        new_throws = st.selectbox("Throws", ["Right", "Left"], key="new_throws")
    if st.button("Add Pitcher"):
        if not new_pname:
            st.warning("Enter pitcher name.")
        else:
            ensure_player(new_pname, team=None, throws=new_throws)
            st.session_state["pitchers"].append({"Name": new_pname, "Throws": new_throws, "Team": None})
            st.success(f"Added pitcher {new_pname}")
            st.rerun()

# -----------------------
# 2 — AtBat selection
# -----------------------
st.header("2 — AtBat Selection")
col1, col2 = st.columns([2,1])
with col1:
    lineup_names = [p["Name"] for p in st.session_state["lineup"]]
    batter_choice = st.selectbox("Select Batter (or Add Batter)", ["-- Select Batter --", "-- Add Batter --"] + lineup_names, key="batter_choice")
    if batter_choice == "-- Add Batter --":
        nb_name = st.text_input("New Batter Name", key="nb_name")
        nb_bats = st.selectbox("Bats", ["Right", "Left", "Switch"], key="nb_bats")
        nb_order = st.number_input("Lineup Position", min_value=1, max_value=99, value=len(st.session_state["lineup"])+1, key="nb_order")
        if st.button("Add Batter to Lineup"):
            if not nb_name:
                st.warning("Enter name.")
            else:
                ensure_player(nb_name, team=None, bats=nb_bats)
                st.session_state["lineup"].append({"Name": nb_name, "Team": None, "Bats": nb_bats, "Order": int(nb_order)})
                st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
                st.success("Added batter.")
                st.rerun()
    elif batter_choice not in ["-- Select Batter --", "-- Add Batter --"]:
        st.write(f"Selected batter: **{batter_choice}**")

with col2:
    pitcher_names = [p["Name"] for p in st.session_state["pitchers"]]
    pitcher_choice = st.selectbox("Select Pitcher (or Add Pitcher)", ["-- Select Pitcher --", "-- Add Pitcher --"] + pitcher_names, key="pitcher_choice")
    if pitcher_choice == "-- Add Pitcher --":
        ap_name = st.text_input("New Pitcher Name", key="ap_name")
        ap_throws = st.selectbox("Throws", ["Right", "Left"], key="ap_throws")
        if st.button("Add Pitcher & Use"):
            if not ap_name:
                st.warning("Enter name.")
            else:
                ensure_player(ap_name, team=None, throws=ap_throws)
                st.session_state["pitchers"].append({"Name": ap_name, "Throws": ap_throws, "Team": None})
                st.success("Added pitcher.")
                st.rerun()
    elif pitcher_choice not in ["-- Select Pitcher --", "-- Add Pitcher --"]:
        st.write(f"Selected pitcher: **{pitcher_choice}**")

# Start AtBat button: only enabled when batter & pitcher picked (or batter added & pitcher picked)
if (batter_choice not in ["-- Select Batter --", "-- Add Batter --"]) and (pitcher_choice not in ["-- Select Pitcher --", "-- Add Pitcher --"]):
    inning_val = st.number_input("Inning", min_value=1, value=1, key="inning_val")
    if st.button("Start AtBat"):
        batter_pid = ensure_player(batter_choice)
        pitcher_pid = ensure_player(pitcher_choice)
        order = next((p["Order"] for p in st.session_state["lineup"] if p["Name"] == batter_choice), None)
        atbat_id = create_atbat(st.session_state["selected_game_id"], batter_pid, pitcher_pid, inning=inning_val, order=order)
        if atbat_id:
            st.session_state["current_atbat_id"] = atbat_id
            st.session_state["balls"] = 0
            st.session_state["strikes"] = 0
            st.session_state["pitch_history"] = []
            st.session_state["last_pitch_summary"] = None
            st.session_state["last_saved_pitch_id"] = None
            st.success(f"AtBat {atbat_id} started.")
            st.rerun()

# -----------------------
# 3 — Pitch Entry
# -----------------------
st.header("3 — Pitch Entry")

if not st.session_state.get("current_atbat_id"):
    st.info("Start an AtBat to enter pitches.")
else:
    atbat_id = st.session_state["current_atbat_id"]
    # load atbat to get batter/pitcher
    atbat_row = supabase.table("AtBats").select("*").eq("AtBatID", atbat_id).execute().data[0]
    batter_id = atbat_row["BatterID"]
    pitcher_id = atbat_row["PitcherID"]
    batter_info = supabase.table("Players").select("Name,Bats").eq("PlayerID", batter_id).execute().data[0]
    pitcher_info = supabase.table("Players").select("Name,Throws").eq("PlayerID", pitcher_id).execute().data[0]

    st.markdown(f"**AtBat {atbat_id}** — Batter: **{batter_info['Name']}** ({batter_info.get('Bats')}) — Pitcher: **{pitcher_info['Name']}** ({pitcher_info.get('Throws')})")
    # last-pitch summary + undo
    if st.session_state["last_pitch_summary"]:
        st.info("Last pitch: " + st.session_state["last_pitch_summary"])
        if st.button("Undo Last Pitch"):
            if st.session_state["pitch_history"]:
                last_pid = st.session_state["pitch_history"].pop()
                try:
                    delete_last_pitch(last_pid)
                    # recompute count from DB
                    pitches = supabase.table("Pitches").select("Balls,Strikes").eq("AtBatID", atbat_id).execute().data or []
                    if pitches:
                        st.session_state["balls"] = pitches[-1].get("Balls", 0)
                        st.session_state["strikes"] = pitches[-1].get("Strikes", 0)
                    else:
                        st.session_state["balls"] = 0
                        st.session_state["strikes"] = 0
                    st.session_state["last_pitch_summary"] = None
                    st.success("Last pitch undone.")
                    st.rerun()
                except Exception as e:
                    st.error("Undo failed: " + str(e))
            else:
                st.warning("No pitch to undo.")

    # next pitch numbers
    pno, poab = next_pitch_numbers_for(atbat_id)
    st.write(f"Next Pitch No: **{pno}** — Pitch of AB: **{poab}**")
    st.write(f"Count: **{st.session_state['balls']}-{st.session_state['strikes']}**")

    st.markdown("**Quick buttons (fast in-game input)**")
    c1, c2, c3 = st.columns(3)
    # quick Ball
    with c1:
        if st.button("Ball Called"):
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
            pitch_called = "Ball Called"
            # For quick actions, use default pitch type/velocity placeholders — coach can use manual for details
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": None,
                "Velocity": None,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"]),
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
                st.session_state["last_saved_pitch_id"] = pid
                st.session_state["last_pitch_summary"] = f"{pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Pitch saved (Ball).")
                st.rerun()
    # quick Swing miss
    with c2:
        if st.button("Strike Swing Miss"):
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
            pitch_called = "Strike Swing Miss"
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": None,
                "Velocity": None,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"]),
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
                st.session_state["last_saved_pitch_id"] = pid
                st.session_state["last_pitch_summary"] = f"{pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Pitch saved (Swing Miss).")
                st.rerun()
    # quick Foul
    with c3:
        if st.button("Foul Ball"):
            if st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
            pitch_called = "Foul Ball"
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": None,
                "Velocity": None,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"]),
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
                st.session_state["last_saved_pitch_id"] = pid
                st.session_state["last_pitch_summary"] = f"{pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Pitch saved (Foul).")
                st.rerun()

    st.markdown("---")
    st.markdown("**Manual pitch entry (detailed)**")
    with st.form("manual_pitch_form"):
        m_ptype = st.selectbox("Pitch Type", ["Fastball","Changeup","Curveball","Slider"], key="m_ptype")
        m_vel = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="m_vel")
        m_zone = st.selectbox("Zone (1-14 or None)", ["None"] + [str(i) for i in range(1,15)], key="m_zone")
        m_called = st.selectbox("Pitch Called", ["Ball Called","Strike Called","Strike Swing Miss","Foul Ball","In Play"], key="m_called")
        m_tagged = st.selectbox("Tagged Hit", ["None","Bunt","Flyball","Groundball","Linedrive"], key="m_tagged")
        m_hitdir = st.selectbox("Hit Direction", ["None","3-4 Hole","5-6 Hole","Catcher","Center Field","First Base","Left Center","Left Field","Middle","Pitcher","Right Center","Right Field","Second Base","Short Stop","Third Base"], key="m_hitdir")
        submit_pitch = st.form_submit_button("Save Manual Pitch")
    if submit_pitch:
        # update counts based on called
        if m_called == "Ball Called":
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
        elif m_called in ["Strike Called","Strike Swing Miss"]:
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
        elif m_called == "Foul Ball":
            if st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
        # compute wel
        wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
        zone_val = None if m_zone == "None" else int(m_zone)
        tagged_val = None if m_tagged == "None" else m_tagged
        hitdir_val = None if m_hitdir == "None" else m_hitdir
        resp = supabase.table("Pitches").insert({
            "AtBatID": atbat_id,
            "PitchNo": pno,
            "PitchOfAB": poab,
            "PitchType": m_ptype,
            "Velocity": m_vel,
            "Zone": zone_val,
            "PitchCalled": m_called,
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
            st.session_state["last_saved_pitch_id"] = pid
            st.session_state["last_pitch_summary"] = f"{m_ptype} {m_vel} — {m_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
            st.success("Manual pitch saved.")
            st.rerun()

# -----------------------
# 4 — Runner Events
# -----------------------
st.header("4 — Runner Events")
# determine current pitch id (most recent)
current_pitch_id = st.session_state.get("last_saved_pitch_id") or (st.session_state["pitch_history"][-1] if st.session_state["pitch_history"] else None)

if not current_pitch_id:
    st.info("Log a pitch first to attach runner events.")
else:
    st.write(f"Logging events for Pitch ID: {current_pitch_id}")
    players_list = supabase.table("Players").select("PlayerID,Name").execute().data or []
    player_map = {p["Name"]: p["PlayerID"] for p in players_list}
    runner_select = st.selectbox("Select Runner", ["-- Select Player --"] + list(player_map.keys()), key="re_runner")
    start_base = st.selectbox("Start Base (1=1st,2=2nd,3=3rd,4=home)", [1,2,3,4], key="re_start")
    end_base = st.selectbox("End Base (1=1st,2=2nd,3=3rd,4=home,0=None)", [1,2,3,4,0], key="re_end", format_func=lambda x: "None" if x==0 else str(x))
    re_event = st.selectbox("Event Type", ["Stolen Base","Caught Stealing","Out on Play","Pickoff","Advanced on Hit","Other"], key="re_evt")
    re_out = st.selectbox("Out Recorded", ["No","Yes"], key="re_out")
    if st.button("Save Runner Event"):
        if runner_select == "-- Select Player --":
            st.warning("Choose runner.")
        else:
            runner_id = player_map[runner_select]
            resp = supabase.table("RunnerEvents").insert({
                "PitchID": current_pitch_id,
                "RunnerID": runner_id,
                "StartBase": start_base,
                "EndBase": None if end_base == 0 else end_base,
                "EventType": re_event,
                "OutRecorded": True if re_out == "Yes" else False
            }).execute()
            if resp.data:
                st.success("Runner event saved.")
            else:
                st.error("Failed to save runner event.")



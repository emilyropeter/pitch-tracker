# app.py
import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Baseball Game Tracker", layout="wide")

# ------------------------
# Supabase connection
# ------------------------
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except KeyError:
    st.error("Supabase credentials missing. Add them to .streamlit/secrets.toml under [supabase].")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------------
# Helpers
# ------------------------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name; create if missing."""
    if not name or str(name).strip() == "":
        return None
    r = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if r.data:
        return r.data[0]["PlayerID"]
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
    resp = supabase.table("Games").insert({
        "HomeTeam": home, "AwayTeam": away, "GameDate": str(gamedate)
    }).execute()
    return resp.data[0]["GameID"] if resp.data else None

def create_atbat(game_id, batter_id, pitcher_id, inning, batter_order=None, lead_off=None):
    """Insert AtBat (BatterID/PitcherID are NOT NULL in your schema)."""
    payload = {
        "GameID": int(game_id),
        "BatterID": int(batter_id),
        "PitcherID": int(pitcher_id),
        "Inning": int(inning),
        "RunsScored": 0,
        "EarnedRuns": 0
    }
    if batter_order is not None:
        payload["BatterOrder"] = int(batter_order)
    if lead_off is not None:
        payload["LeadOff"] = bool(lead_off)
    resp = supabase.table("AtBats").insert(payload).execute()
    return resp.data[0]["AtBatID"] if resp.data else None

def update_atbat(atbat_id, updates: dict):
    return supabase.table("AtBats").update(updates).eq("AtBatID", atbat_id).execute()

def next_pitch_numbers_for(atbat_id):
    """Return (next global PitchNo, next PitchOfAB)."""
    r1 = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
    last_global = r1.data[0]["PitchNo"] if r1.data else 0
    r2 = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
    last_poab = r2.data[0]["PitchOfAB"] if r2.data else 0
    return last_global + 1, last_poab + 1

def compute_wel(balls, strikes):
    """Early: (0-0,0-1,1-0,1-1); Win: (0-2,1-2); Lose: (2-0,2-1)."""
    t = (balls, strikes)
    if t in [(0,0),(0,1),(1,0),(1,1)]:
        return "E"
    if t in [(0,2),(1,2)]:
        return "W"
    if t in [(2,0),(2,1)]:
        return "L"
    return None

def insert_pitch(atbat_id, pitch_no, pitch_of_ab, pitch_type, velocity, zone, pitch_called, balls, strikes, wel, tagged, hitdir, kpi):
    payload = {
        "AtBatID": int(atbat_id),
        "PitchNo": int(pitch_no),
        "PitchOfAB": int(pitch_of_ab),
        "PitchType": pitch_type,
        "Velocity": None if velocity in (None, "") else float(velocity),
        "Zone": None if zone in (None, "") else int(zone),
        "PitchCalled": pitch_called,
        "WEL": wel,
        "Balls": int(balls),
        "Strikes": int(strikes),
        "TaggedHit": tagged,
        "HitDirection": hitdir,
        "KPI": kpi if kpi not in (None, "") else None
    }
    return supabase.table("Pitches").insert(payload).execute()

def delete_last_pitch(pitch_id):
    return supabase.table("Pitches").delete().eq("PitchID", pitch_id).execute()

# ------------------------
# Session defaults
# ------------------------
defaults = {
    "lineup": [],             # [{Name, Team, Bats, Order, PlayerID}]
    "pitchers": [],           # [{Name, Team, Throws, PlayerID}]
    "selected_game_id": None,
    "current_batter_id": None,
    "current_pitcher_id": None,
    "current_atbat_id": None,
    "balls": 0,
    "strikes": 0,
    "pitch_history": [],      # [PitchID, ...]
    "last_pitch_summary": None,
    "last_saved_pitch_id": None,
    # quick entry state + summary log
    "quick_pitch_type": None,
    "quick_pitch_called": None,
    "quick_vel": 0.0,
    "quick_zone": "None",
    "event_log": []           # newest-first strings
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

def add_to_summary(line: str):
    st.session_state["event_log"].insert(0, line)  # newest first

# ------------------------
# UI - Header
# ------------------------
st.title("⚾ Baseball Game Tracker")
st.caption("Quick buttons for in-game use. Manual entry preserved. Undo last pitch. Runner events + running summary.")

# ------------------------
# 1) Setup: Games / Lineup / Pitchers
# ------------------------
with st.expander("1 — Game Setup & Lineup", expanded=True):
    col1, col2, col3 = st.columns([3,3,2])

    # Game select / create
    with col1:
        games = supabase.table("Games").select("GameID, GameDate, HomeTeam, AwayTeam").order("GameDate", desc=True).execute().data or []
        game_map = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}
        sel_game = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_map.keys()))
        if sel_game == "-- Add New Game --":
            new_home = st.text_input("Home Team")
            new_away = st.text_input("Away Team")
            new_date = st.date_input("Game Date", value=date.today())
            if st.button("Create Game"):
                gid = create_game(new_home, new_away, new_date)
                if gid:
                    st.success("Game created. Re-open select to pick it.")
                    st.rerun()
                else:
                    st.error("Failed to create game.")
            st.stop()
        else:
            st.session_state["selected_game_id"] = game_map[sel_game]
            st.write("Selected:", sel_game)

    # Lineup (hitters)
    with col2:
        st.subheader("Starting Lineup / Subs")
        hname = st.text_input("Hitter name", key="h_name")
        hbats = st.selectbox("Bats", ["Right", "Left", "Switch"], key="h_bats")
        hslot_default = len(st.session_state["lineup"]) + 1
        hslot = st.number_input("Lineup slot", min_value=1, max_value=99, value=hslot_default, key="h_slot")
        if st.button("Add Hitter"):
            if not hname:
                st.warning("Enter hitter name.")
            else:
                pid = ensure_player(hname, bats=hbats)
                st.session_state["lineup"].append({"Name": hname, "Team": None, "Bats": hbats, "Order": int(hslot), "PlayerID": pid})
                st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
                st.success(f"Added {hname}")
                st.rerun()
        if st.session_state["lineup"]:
            st.write("Lineup:")
            for i, p in enumerate(st.session_state["lineup"]):
                c0, c1 = st.columns([6,1])
                c0.write(f"{p['Order']}. {p['Name']} ({p['Bats']})")
                if c1.button(f"RemoveHitter-{i}"):
                    st.session_state["lineup"].pop(i)
                    st.success("Removed hitter.")
                    st.rerun()

    # Pitchers
    with col3:
        st.subheader("Pitchers")
        pname = st.text_input("Pitcher name", key="p_name")
        p_throws = st.selectbox("Throws", ["Right", "Left"], key="p_throws")
        if st.button("Add Pitcher"):
            if not pname:
                st.warning("Enter pitcher name.")
            else:
                pid = ensure_player(pname, throws=p_throws)
                st.session_state["pitchers"].append({"Name": pname, "Team": None, "Throws": p_throws, "PlayerID": pid})
                st.success(f"Added pitcher {pname}")
                st.rerun()
        if st.session_state["pitchers"]:
            st.write("Pitchers:")
            for j, q in enumerate(st.session_state["pitchers"]):
                cc0, cc1 = st.columns([6,1])
                cc0.write(f"{q['Name']} ({q['Throws']})")
                if cc1.button(f"RemovePitch-{j}"):
                    st.session_state["pitchers"].pop(j)
                    st.success("Removed pitcher.")
                    st.rerun()

# ------------------------
# 2) Select AtBat: batter & pitcher
# ------------------------
st.header("2 — Select AtBat (choose batter and pitcher)")

colB1, colB2, colB3 = st.columns([3,3,2])

with colB1:
    lineup_names = [x["Name"] for x in st.session_state["lineup"]]
    batter_choice = st.selectbox("Batter (from lineup or Add)", ["-- Select --", "-- Add Batter --"] + lineup_names, key="b_choice")
    if batter_choice == "-- Add Batter --":
        add_name = st.text_input("New Batter Name", key="add_b_name")
        add_bats = st.selectbox("Bats", ["Right", "Left", "Switch"], key="add_b_bats")
        add_slot_val = len(st.session_state["lineup"]) + 1
        add_slot = st.number_input("Lineup slot", min_value=1, max_value=99, value=add_slot_val, key="add_b_slot")
        if st.button("Add to lineup"):
            if not add_name:
                st.warning("Enter name.")
            else:
                pid = ensure_player(add_name, bats=add_bats)
                st.session_state["lineup"].append({"Name": add_name, "Team": None, "Bats": add_bats, "Order": int(add_slot), "PlayerID": pid})
                st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
                st.success("Added batter.")
                st.rerun()
    elif batter_choice not in ["-- Select --", "-- Add Batter --"]:
        sel = next((x for x in st.session_state["lineup"] if x["Name"] == batter_choice), None)
        if sel:
            st.session_state["current_batter_id"] = sel["PlayerID"]
            st.write(f"Selected batter: {sel['Name']} (slot {sel['Order']})")

with colB2:
    pitch_names = [x["Name"] for x in st.session_state["pitchers"]]
    pitcher_choice = st.selectbox("Pitcher (from setup or Add)", ["-- Select --", "-- Add Pitcher --"] + pitch_names, key="p_choice")
    if pitcher_choice == "-- Add Pitcher --":
        newp_name = st.text_input("Pitcher Name", key="newp_name")
        newp_throws = st.selectbox("Throws", ["Right", "Left"], key="newp_throws")
        if st.button("Add & Use Pitcher"):
            if not newp_name:
                st.warning("Enter name.")
            else:
                pid = ensure_player(newp_name, throws=newp_throws)
                st.session_state["pitchers"].append({"Name": newp_name, "Team": None, "Throws": newp_throws, "PlayerID": pid})
                st.session_state["current_pitcher_id"] = pid
                st.success("Added pitcher.")
                st.rerun()
    elif pitcher_choice not in ["-- Select --", "-- Add Pitcher --"]:
        sp = next((x for x in st.session_state["pitchers"] if x["Name"] == pitcher_choice), None)
        if sp:
            st.session_state["current_pitcher_id"] = sp["PlayerID"]
            st.write(f"Selected pitcher: {sp['Name']}")

with colB3:
    inning_val = st.number_input("Inning", min_value=1, value=1)
    # LeadOff ONLY (LeadOffOn moved to Finish AtBat)
    lead_off_sel = st.selectbox("LeadOff", ["Select", "Yes", "No"], key="lead_off_sel")
    if st.button("Start AtBat"):
        if not st.session_state["selected_game_id"]:
            st.error("Select a game in Setup first.")
        elif not st.session_state["current_batter_id"] or not st.session_state["current_pitcher_id"]:
            st.error("Select batter and pitcher (from setup or add them).")
        else:
            lo_val = None if lead_off_sel == "Select" else (lead_off_sel == "Yes")
            atbat_id = create_atbat(
                st.session_state["selected_game_id"],
                st.session_state["current_batter_id"],
                st.session_state["current_pitcher_id"],
                inning_val,
                batter_order=None,
                lead_off=lo_val
            )
            if atbat_id:
                st.session_state["current_atbat_id"] = atbat_id
                st.session_state["balls"] = 0
                st.session_state["strikes"] = 0
                st.session_state["pitch_history"] = []
                st.session_state["last_pitch_summary"] = None
                st.session_state["last_saved_pitch_id"] = None
                st.success(f"AtBat {atbat_id} created.")
                st.rerun()
            else:
                st.error("Failed to create AtBat. Check DB constraints.")

# ------------------------
# 3) Pitch Entry — QUICK BUTTONS (above manual)
# ------------------------
st.header("3 — Pitch Entry (Quick Buttons)")

if not st.session_state["current_atbat_id"]:
    st.info("Start an AtBat (choose batter & pitcher then Start AtBat).")
else:
    atbat_id = st.session_state["current_atbat_id"]
    pno, poab = next_pitch_numbers_for(atbat_id)
    st.write(f"Next PitchNo: **{pno}** — PitchOfAB: **{poab}**")
    st.write(f"Count: **{st.session_state['balls']}-{st.session_state['strikes']}**")

    # Last pitch + undo
    if st.session_state["last_pitch_summary"]:
        st.info("Last pitch: " + st.session_state["last_pitch_summary"])
        if st.button("Undo Last Pitch"):
            if st.session_state["pitch_history"]:
                last_pid = st.session_state["pitch_history"].pop()
                try:
                    delete_last_pitch(last_pid)
                    rec = supabase.table("Pitches").select("Balls,Strikes").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute().data or []
                    if rec:
                        st.session_state["balls"] = rec[0].get("Balls", 0)
                        st.session_state["strikes"] = rec[0].get("Strikes", 0)
                    else:
                        st.session_state["balls"] = 0
                        st.session_state["strikes"] = 0
                    st.session_state["last_pitch_summary"] = None
                    st.success("Undo successful.")
                    st.rerun()
                except Exception as e:
                    st.error("Undo failed: " + str(e))
            else:
                st.warning("No pitch to undo.")

    # --- Quick Pitch Type buttons (horizontal)
    st.markdown("**Pitch Type**")
    pt_cols = st.columns(5)
    types = ["Fastball", "Slider", "Curveball", "Changeup", "Cutter"]
    for i, t in enumerate(types):
        if pt_cols[i].button(t, key=f"pt_{t}"):
            st.session_state["quick_pitch_type"] = t

    st.caption(f"Selected type: {st.session_state['quick_pitch_type'] or '—'}")

    # --- Quick Pitch Called buttons (horizontal)
    st.markdown("**Pitch Called**")
    pc_cols = st.columns(5)
    calleds = ["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"]
    for i, c in enumerate(calleds):
        if pc_cols[i].button(c, key=f"pc_{c}"):
            st.session_state["quick_pitch_called"] = c

    st.caption(f"Selected called: {st.session_state['quick_pitch_called'] or '—'}")

    # Optional quick velocity + zone
    qc1, qc2 = st.columns(2)
    with qc1:
        st.session_state["quick_vel"] = st.number_input("Velocity (mph, optional)", min_value=0.0, step=0.1, value=float(st.session_state["quick_vel"]), key="quick_vel_inp")
    with qc2:
        st.session_state["quick_zone"] = st.selectbox("Zone (optional)", ["None"] + [str(i) for i in range(1,15)], index=(0 if st.session_state["quick_zone"]=="None" else int(st.session_state["quick_zone"])), key="quick_zone_sel")

    # Submit quick pitch
    if st.button("Submit Pitch"):
        if not st.session_state["quick_pitch_type"] or not st.session_state["quick_pitch_called"]:
            st.warning("Pick a Pitch Type and a Pitch Called first.")
        else:
            # Update counts from result
            called = st.session_state["quick_pitch_called"]
            if called == "Ball Called":
                st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
            elif called in ["Strike Called", "Strike Swing Miss"]:
                st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
            elif called == "Foul Ball" and st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
            elif called == "In Play" and st.session_state["strikes"] < 3:
                st.session_state["strikes"] += 1

            wel = compute_wel(st.session_state["balls"], st.session_state["strikes"])
            zone_val = None if st.session_state["quick_zone"] == "None" else int(st.session_state["quick_zone"])

            r = insert_pitch(
                atbat_id=atbat_id,
                pitch_no=pno,
                pitch_of_ab=poab,
                pitch_type=st.session_state["quick_pitch_type"],
                velocity=st.session_state["quick_vel"],
                zone=zone_val,
                pitch_called=called,
                balls=st.session_state["balls"],
                strikes=st.session_state["strikes"],
                wel=wel,
                tagged=None,
                hitdir=None,
                kpi=None
            )
            if r.data:
                pid = r.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_saved_pitch_id"] = pid
                st.session_state["last_pitch_summary"] = f"{st.session_state['quick_pitch_type']} {st.session_state['quick_vel']} — {called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                add_to_summary(f"Pitch {pno}: {st.session_state['quick_pitch_type']} — {called}  |  {st.session_state['balls']}-{st.session_state['strikes']}")
                # reset quick selections/fields
                st.session_state["quick_pitch_type"] = None
                st.session_state["quick_pitch_called"] = None
                st.session_state["quick_vel"] = 0.0
                st.session_state["quick_zone"] = "None"
                st.success("Pitch saved.")
                st.rerun()
            else:
                st.error("Pitch not saved. Check DB schema.")

    # ------------------------
    # Manual Pitch Form (kept below)
    # ------------------------
    st.markdown("---")
    st.markdown("**Manual pitch entry (detail)**")
    with st.form("manual_pitch_form"):
        m_type = st.selectbox("Pitch Type", ["Fastball", "Changeup", "Curveball", "Slider", "Cutter"])
        m_vel = st.number_input("Velocity (mph)", min_value=0.0, step=0.1)
        m_zone = st.selectbox("Zone (1-14 or None)", ["None"] + [str(i) for i in range(1,15)])
        m_called = st.selectbox("Pitch Called", ["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"])
        m_tagged = st.selectbox("Tagged Hit", ["None", "Bunt", "Flyball", "Groundball", "Linedrive"])
        m_hitdir = st.selectbox("Hit Direction", ["None","3-4 Hole","5-6 Hole","Catcher","Center Field","First Base","Left Center","Left Field","Middle","Pitcher","Right Center","Right Field","Second Base","Short Stop","Third Base"])
        m_kpi = st.text_input("KPI / Notes (optional)")
        submit_pitch = st.form_submit_button("Save Manual Pitch")

    if submit_pitch:
        # Update counts from result
        if m_called == "Ball Called":
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
        elif m_called in ["Strike Called", "Strike Swing Miss"]:
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
        elif m_called == "Foul Ball" and st.session_state["strikes"] < 2:
            st.session_state["strikes"] += 1
        elif m_called == "In Play" and st.session_state["strikes"] < 3:
            st.session_state["strikes"] += 1

        wel = compute_wel(st.session_state["balls"], st.session_state["strikes"])
        zone_val = None if m_zone == "None" else int(m_zone)
        tagged_val = None if m_tagged == "None" else m_tagged
        hitdir_val = None if m_hitdir == "None" else m_hitdir

        r = insert_pitch(atbat_id, pno, poab, m_type, m_vel, zone_val, m_called,
                         st.session_state["balls"], st.session_state["strikes"], wel,
                         tagged_val, hitdir_val, m_kpi)
        if r.data:
            pid = r.data[0]["PitchID"]
            st.session_state["pitch_history"].append(pid)
            st.session_state["last_saved_pitch_id"] = pid
            st.session_state["last_pitch_summary"] = f"{m_type} {m_vel} — {m_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
            add_to_summary(f"Pitch {pno}: {m_type} — {m_called}  |  {st.session_state['balls']}-{st.session_state['strikes']}")
            st.success("Manual pitch saved.")
            st.rerun()
        else:
            st.error("Pitch not saved. Check DB schema.")

# ------------------------
# 4) Finish AtBat (LeadOffOn here; simplified PlayResult; specials -> KorBB)
# ------------------------
st.header("4 — Finish AtBat (record result, clear at-bat)")

if st.session_state["current_atbat_id"]:
    # Simplified PlayResult list (no Pickoff/CaughtStealing/4PW/2SW here)
    play_result_options = [
        "1B", "2B", "3B", "HR",
        "Walk", "Intentional Walk",
        "Strikeout Looking", "Strikeout Swinging",
        "HitByPitch", "GroundOut", "FlyOut", "Error", "FC", "SAC", "SACFly"
    ]
    finish_play = st.selectbox("Play Result", ["-- Select --"] + play_result_options)

    # Special Walk Type (optional) -> store in KorBB for simplicity
    special_walk = None
    if finish_play in ["Walk", "Intentional Walk"]:
        special_walk = st.selectbox(
            "Special Walk Type (optional)",
            ["None", "4 Pitch Walk", "2 Strike Walk", "2 Out Walk"],
            key="special_walk"
        )

    # LeadOffOn here
    lead_off_on_sel = st.selectbox("LeadOff On", ["Select", "Yes", "No"], key="finish_lead_off_on")

    finish_runs = st.number_input("Runs Scored (if any)", min_value=0, value=0)
    finish_earned = st.number_input("Earned Runs", min_value=0, value=0)

    # Optional KorBB fallback
    korbb_choice = st.selectbox("KorBB (optional)", ["None", "Strikeout Looking", "Strikeout Swinging", "Walk", "Intentional Walk"])

    if st.button("Finish AtBat"):
        updates = {}
        if finish_play != "-- Select --":
            updates["PlayResult"] = finish_play
        updates["RunsScored"] = int(finish_runs)
        updates["EarnedRuns"] = int(finish_earned)

        if lead_off_on_sel != "Select":
            updates["LeadOffOn"] = (lead_off_on_sel == "Yes")

        # Store special walk label in KorBB (simple version)
        if special_walk and special_walk != "None":
            updates["KorBB"] = special_walk
        elif korbb_choice != "None":
            updates["KorBB"] = korbb_choice

        try:
            upd = update_atbat(st.session_state["current_atbat_id"], updates)
            if upd.data:
                st.success("AtBat updated.")
                add_to_summary(f"AtBat finished: {updates.get('PlayResult','Result')}  |  Runs {updates.get('RunsScored',0)}  ER {updates.get('EarnedRuns',0)}")
                # Clear state for next AB
                st.session_state["current_atbat_id"] = None
                st.session_state["balls"] = 0
                st.session_state["strikes"] = 0
                st.session_state["pitch_history"] = []
                st.session_state["last_pitch_summary"] = None
                st.session_state["last_saved_pitch_id"] = None
                st.rerun()
            else:
                st.error("Failed to update AtBat.")
        except Exception as e:
            st.error(f"Error updating AtBat: {e}")
else:
    st.info("No active at-bat. Start one in step 2.")

# ------------------------
# 5) Runner Events (attach to last pitch)
# ------------------------
st.header("5 — Runner Events (attach to last pitch)")

current_pid = st.session_state.get("last_saved_pitch_id") or (st.session_state["pitch_history"][-1] if st.session_state["pitch_history"] else None)
if not current_pid:
    st.info("Log a pitch first to attach runner events.")
else:
    st.write(f"Attaching runner events to PitchID: {current_pid}")
    players = supabase.table("Players").select("PlayerID, Name").order("Name", desc=False).execute().data or []
    names = [p["Name"] for p in players]
    sel_names = st.multiselect("Select one or more runners", names)
    start_base = st.selectbox("Start base", [1,2,3,4], index=0)
    end_base = st.selectbox("End base (0=None)", [0,1,2,3,4], index=0, format_func=lambda x: "None" if x==0 else str(x))
    event_type = st.selectbox("Event Type", ["Stolen Base","Caught Stealing","Out on Play","Pickoff","Advanced on Hit","Other"])
    out_recorded = st.selectbox("Out Recorded", ["No","Yes"])
    if st.button("Save Runner Events"):
        if not sel_names:
            st.warning("Choose at least one runner.")
        else:
            created = 0
            for nm in sel_names:
                pid = next((p["PlayerID"] for p in players if p["Name"] == nm), None)
                if pid is None:
                    continue
                payload = {
                    "PitchID": int(current_pid),
                    "RunnerID": int(pid),
                    "StartBase": int(start_base),
                    "EndBase": None if end_base == 0 else int(end_base),
                    "EventType": event_type,
                    "OutRecorded": True if out_recorded == "Yes" else False
                }
                try:
                    r = supabase.table("RunnerEvents").insert(payload).execute()
                    if r.data:
                        created += 1
                        arrow = f"{start_base}→{end_base if end_base!=0 else '-'}"
                        add_to_summary(f"Runner {nm}: {event_type}  |  {arrow}  |  Out={payload['OutRecorded']}")
                except Exception as e:
                    st.error(f"Failed for {nm}: {e}")
            if created:
                st.success(f"Saved {created} runner events.")
            else:
                st.warning("No runner events saved.")

# ------------------------
# Running Summary (session-only, newest first)
# ------------------------
st.markdown("---")
st.subheader("Running Summary (session)")
if st.session_state["event_log"]:
    for line in st.session_state["event_log"]:
        st.write("• " + line)
else:
    st.caption("No events yet. Pitch or record a runner event to see entries here.")

# Footer
st.caption(f"Game ID: {st.session_state.get('selected_game_id')}  |  AtBat ID: {st.session_state.get('current_atbat_id')}  |  Count: {st.session_state['balls']}-{st.session_state['strikes']}")

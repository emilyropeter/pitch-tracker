
# app.py — Full Baseball Game Tracker (Streamlit + Supabase)
# Includes: setup, lineup with suggestions & duplicate checks, at-bat flow,
# quick + manual pitch entry (auto balls/strikes + WEL), finish at-bat,
# runner events, undo, and running summary — all in ONE file.

import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Baseball Game Tracker", layout="wide")

# ---------------------------------------------------------
# Supabase connection
# ---------------------------------------------------------
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except KeyError:
    st.error("Supabase credentials missing. Add them to .streamlit/secrets.toml under [supabase].")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name; create if missing."""
    if not name or str(name).strip() == "":
        return None
    r = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if r.data:
        return r.data[0]["PlayerID"]
    payload = {"Name": name}
    if team: payload["Team"] = team
    if throws: payload["Throws"] = throws
    if bats: payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    return created.data[0]["PlayerID"] if created.data else None

def create_game(home, away, gamedate):
    resp = supabase.table("Games").insert({
        "HomeTeam": home, "AwayTeam": away, "GameDate": str(gamedate)
    }).execute()
    return resp.data[0]["GameID"] if resp.data else None

def create_atbat(game_id, batter_id, pitcher_id, inning, batter_order=None, lead_off=None):
    payload = {
        "GameID": int(game_id),
        "BatterID": int(batter_id),
        "PitcherID": int(pitcher_id),
        "Inning": int(inning),
        "RunsScored": 0,
        "EarnedRuns": 0
    }
    if batter_order: payload["BatterOrder"] = int(batter_order)
    if lead_off is not None: payload["LeadOff"] = bool(lead_off)
    resp = supabase.table("AtBats").insert(payload).execute()
    return resp.data[0]["AtBatID"] if resp.data else None

def update_atbat(atbat_id, updates: dict):
    return supabase.table("AtBats").update(updates).eq("AtBatID", atbat_id).execute()

def next_pitch_numbers_for(atbat_id):
    r1 = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
    last_global = r1.data[0]["PitchNo"] if r1.data else 0
    r2 = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
    last_poab = r2.data[0]["PitchOfAB"] if r2.data else 0
    return last_global + 1, last_poab + 1

def compute_wel(balls, strikes):
    # Early: (0-0, 0-1, 1-0, 1-1)
    # Win:   (0-2, 1-2)
    # Lose:  (2-0, 2-1)
    if (balls, strikes) in [(0,0),(0,1),(1,0),(1,1)]: return "E"
    if (balls, strikes) in [(0,2),(1,2)]: return "W"
    if (balls, strikes) in [(2,0),(2,1)]: return "L"
    return None

def insert_pitch(atbat_id, pitch_no, pitch_of_ab, pitch_type, velocity, zone, pitch_called,
                 balls, strikes, wel, tagged, hitdir, kpi):
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

def add_to_summary(line):
    st.session_state["event_log"].insert(0, line)

# ---------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------
defaults = {
    "lineup": [], "pitchers": [],
    "selected_game_id": None,
    "current_batter_id": None,
    "current_pitcher_id": None,
    "current_atbat_id": None,
    "balls": 0, "strikes": 0, "pitch_history": [],
    "last_pitch_summary": None, "last_saved_pitch_id": None,
    "quick_pitch_type": None, "quick_pitch_called": None,
    "quick_vel": 0.0, "quick_zone": "None",
    "event_log": []
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------
# 1 — Game Setup & Lineup
# ---------------------------------------------------------
st.title("⚾ Baseball Game Tracker")
st.caption("Quick buttons + manual entry, runner events, undo, and a running summary.")

with st.expander("1 — Game Setup & Lineup", expanded=True):
    col1, col2, col3 = st.columns([3,3,2])

    with col1:
        games = supabase.table("Games").select("GameID, GameDate, HomeTeam, AwayTeam").order("GameDate", desc=True).execute().data or []
        game_map = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}
        sel_game = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_map.keys()))
        if sel_game == "-- Add New Game --":
            home = st.text_input("Home Team")
            away = st.text_input("Away Team")
            gamedate = st.date_input("Game Date", value=date.today())
            if st.button("Create Game"):
                gid = create_game(home, away, gamedate)
                if gid:
                    st.success("Game created. Re-open select to pick it.")
                    st.rerun()
                else:
                    st.error("Failed to create game.")
            st.stop()
        else:
            st.session_state["selected_game_id"] = game_map[sel_game]
            st.info(f"Selected Game: {sel_game}")

    existing_players = supabase.table("Players").select("Name").execute().data or []
    all_names = [p["Name"] for p in existing_players]

    with col2:
        st.subheader("Lineup")
        hname = st.text_input("Hitter name")
        hbats = st.selectbox("Bats", ["Right", "Left", "Switch"])
        if hname:
            matches = [n for n in all_names if hname.lower() in n.lower()]
            if matches:
                st.caption("Existing players: " + ", ".join(matches[:5]))
        if st.button("Add Hitter"):
            if not hname:
                st.warning("Enter a name.")
            elif any(p["Name"].lower() == hname.lower() for p in st.session_state["lineup"]):
                st.error("⚠️ Batter already in lineup.")
            else:
                pid = ensure_player(hname, bats=hbats)
                order = len(st.session_state["lineup"]) + 1
                st.session_state["lineup"].append({"Name": hname, "Bats": hbats, "Order": order, "PlayerID": pid})
                st.success(f"Added {hname} as #{order}")
                st.rerun()
        for i, p in enumerate(st.session_state["lineup"]):
            c1, c2 = st.columns([6,1])
            c1.write(f"{p['Order']}. {p['Name']} ({p['Bats']})")
            if c2.button("❌", key=f"delh{i}"):
                st.session_state["lineup"].pop(i)
                st.rerun()

    with col3:
        st.subheader("Pitchers")
        pname = st.text_input("Pitcher name")
        pthrows = st.selectbox("Throws", ["Right", "Left"])
        if pname:
            matches = [n for n in all_names if pname.lower() in n.lower()]
            if matches: st.caption("Existing players: " + ", ".join(matches[:5]))
        if st.button("Add Pitcher"):
            if not pname:
                st.warning("Enter pitcher name.")
            elif any(p["Name"].lower() == pname.lower() for p in st.session_state["pitchers"]):
                st.error("⚠️ Pitcher already added.")
            else:
                pid = ensure_player(pname, throws=pthrows)
                st.session_state["pitchers"].append({"Name": pname, "Throws": pthrows, "PlayerID": pid})
                st.success(f"Added pitcher {pname}")
                st.rerun()
        for j, q in enumerate(st.session_state["pitchers"]):
            c1, c2 = st.columns([6,1])
            c1.write(f"{q['Name']} ({q['Throws']})")
            if c2.button("❌", key=f"delp{j}"):
                st.session_state["pitchers"].pop(j)
                st.rerun()

# ---------------------------------------------------------
# 2 — Select AtBat
# ---------------------------------------------------------
st.header("2 — Select AtBat")
col1, col2, col3 = st.columns([3,3,2])

with col1:
    batters = [x["Name"] for x in st.session_state["lineup"]]
    b_choice = st.selectbox("Batter", ["-- Select --"] + batters)
    if b_choice != "-- Select --":
        st.session_state["current_batter_id"] = next(x["PlayerID"] for x in st.session_state["lineup"] if x["Name"] == b_choice)

with col2:
    pitchers = [x["Name"] for x in st.session_state["pitchers"]]
    p_choice = st.selectbox("Pitcher", ["-- Select --"] + pitchers)
    if p_choice != "-- Select --":
        st.session_state["current_pitcher_id"] = next(x["PlayerID"] for x in st.session_state["pitchers"] if x["Name"] == p_choice)

with col3:
    inning = st.number_input("Inning", min_value=1, value=1)
    lead_off_sel = st.selectbox("LeadOff", ["Select", "Yes", "No"])
    if st.button("Start AtBat"):
        if not st.session_state["current_batter_id"] or not st.session_state["current_pitcher_id"]:
            st.warning("Select both batter and pitcher.")
        else:
            lead = None if lead_off_sel == "Select" else (lead_off_sel == "Yes")
            atbat_id = create_atbat(
                st.session_state["selected_game_id"],
                st.session_state["current_batter_id"],
                st.session_state["current_pitcher_id"],
                inning,
                lead_off=lead
            )
            if atbat_id:
                st.session_state["current_atbat_id"] = atbat_id
                st.session_state["balls"] = 0
                st.session_state["strikes"] = 0
                st.session_state["pitch_history"].clear()
                st.session_state["last_pitch_summary"] = None
                st.session_state["last_saved_pitch_id"] = None
                st.success(f"AtBat #{atbat_id} started.")
                st.rerun()

# ---------------------------------------------------------
# 3 — Pitch Entry (Quick + Manual)
# ---------------------------------------------------------
st.header("3 — Pitch Entry")
if not st.session_state["current_atbat_id"]:
    st.info("Start an AtBat to enter pitches.")
else:
    atbat_id = st.session_state["current_atbat_id"]
    pno, poab = next_pitch_numbers_for(atbat_id)
    st.write(f"Next PitchNo: **{pno}** — PitchOfAB: **{poab}**")
    st.write(f"Count: **{st.session_state['balls']}-{st.session_state['strikes']}**")

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

    # Quick buttons — horizontal
    st.subheader("Quick Pitch Buttons")
    pt_cols = st.columns(5)
    for i, t in enumerate(["Fastball", "Slider", "Curveball", "Changeup", "Cutter"]):
        if pt_cols[i].button(t, key=f"pt_{t}"):
            st.session_state["quick_pitch_type"] = t
    st.caption(f"Selected type: {st.session_state['quick_pitch_type'] or '—'}")

    pc_cols = st.columns(5)
    for i, c in enumerate(["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"]):
        if pc_cols[i].button(c, key=f"pc_{c}"):
            st.session_state["quick_pitch_called"] = c
    st.caption(f"Selected called: {st.session_state['quick_pitch_called'] or '—'}")

    qc1, qc2 = st.columns(2)
    with qc1:
        st.session_state["quick_vel"] = st.number_input("Velocity (mph, optional)", min_value=0.0, step=0.1, value=float(st.session_state["quick_vel"]), key="quick_vel_inp")
    with qc2:
        zone_opts = ["None"] + [str(i) for i in range(1,15)]
        current_idx = 0 if st.session_state["quick_zone"] == "None" else int(st.session_state["quick_zone"])
        st.session_state["quick_zone"] = st.selectbox("Zone (optional)", zone_opts, index=current_idx, key="quick_zone_sel")

    if st.button("Submit Pitch"):
        if not st.session_state["quick_pitch_type"] or not st.session_state["quick_pitch_called"]:
            st.warning("Pick a Pitch Type and a Pitch Called first.")
        else:
            called = st.session_state["quick_pitch_called"]
            # Update count automatically
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
                # reset quick selections
                st.session_state["quick_pitch_type"] = None
                st.session_state["quick_pitch_called"] = None
                st.session_state["quick_vel"] = 0.0
                st.session_state["quick_zone"] = "None"
                st.success("Pitch saved.")
                st.rerun()
            else:
                st.error("Pitch not saved. Check DB schema.")

    # Manual entry
    st.markdown("---")
    st.subheader("Manual Pitch Entry")
    with st.form("manual_pitch_form"):
        m_type = st.selectbox("Pitch Type", ["Fastball", "Slider", "Curveball", "Changeup", "Cutter"])
        m_vel = st.number_input("Velocity (mph)", min_value=0.0, step=0.1)
        m_zone = st.selectbox("Zone (1-14 or None)", ["None"] + [str(i) for i in range(1,15)])
        m_called = st.selectbox("Pitch Called", ["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"])
        m_tagged = st.selectbox("Tagged Hit", ["None", "Bunt", "Flyball", "Groundball", "Linedrive"])
        m_hitdir = st.selectbox("Hit Direction", ["None","3-4 Hole","5-6 Hole","Catcher","Center Field","First Base","Left Center","Left Field","Middle","Pitcher","Right Center","Right Field","Second Base","Short Stop","Third Base"])
        m_kpi = st.text_input("KPI / Notes (optional)")
        submit_pitch = st.form_submit_button("Save Manual Pitch")

    if submit_pitch:
        # update counts
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

# ---------------------------------------------------------
# 4 — Finish AtBat (result + LeadOffOn here)
# ---------------------------------------------------------
st.header("4 — Finish AtBat")
if st.session_state["current_atbat_id"]:
    play_result_options = [
        "1B", "2B", "3B", "HR",
        "Walk", "Intentional Walk",
        "Strikeout Looking", "Strikeout Swinging",
        "HitByPitch", "GroundOut", "FlyOut", "Error", "FC", "SAC", "SACFly"
    ]
    finish_play = st.selectbox("Play Result", ["-- Select --"] + play_result_options)
    lead_off_on_sel = st.selectbox("LeadOff On", ["Select", "Yes", "No"])
    finish_runs = st.number_input("Runs Scored", min_value=0, value=0)
    finish_earned = st.number_input("Earned Runs", min_value=0, value=0)

    if st.button("Finish AtBat"):
        updates = {
            "RunsScored": int(finish_runs),
            "EarnedRuns": int(finish_earned)
        }
        if finish_play != "-- Select --":
            updates["PlayResult"] = finish_play
        if lead_off_on_sel != "Select":
            updates["LeadOffOn"] = (lead_off_on_sel == "Yes")

        try:
            upd = update_atbat(st.session_state["current_atbat_id"], updates)
            if upd.data:
                add_to_summary(f"AtBat finished: {updates.get('PlayResult','Result')} | Runs {updates['RunsScored']} ER {updates['EarnedRuns']}")
                st.success("AtBat updated & closed.")
                # clear at-bat state
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
    st.info("No active at-bat. Start one above in step 2.")

# ---------------------------------------------------------
# 5 — Runner Events (attach to last pitch)
# ---------------------------------------------------------
st.header("5 — Runner Events")
current_pid = st.session_state.get("last_saved_pitch_id") or (st.session_state["pitch_history"][-1] if st.session_state["pitch_history"] else None)
if not current_pid:
    st.info("Log a pitch first to attach runner events.")
else:
    st.write(f"Attaching events to PitchID: {current_pid}")
    players = supabase.table("Players").select("PlayerID, Name").order("Name", desc=False).execute().data or []
    player_map = {p["Name"]: p["PlayerID"] for p in players}

    runner = st.selectbox("Runner", ["-- Select --"] + list(player_map.keys()))
    start_base = st.selectbox("Start Base", [1,2,3,4])
    end_base = st.selectbox("End Base (0=None)", [0,1,2,3,4], format_func=lambda x: "None" if x==0 else str(x))
    event_type = st.selectbox("Event Type", ["Stolen Base","Caught Stealing","Pickoff","Out on Play","Advanced on Hit","Other"])
    out_recorded = st.selectbox("Out Recorded", ["No","Yes"])

    if st.button("Save Runner Event"):
        if runner == "-- Select --":
            st.warning("Choose a runner.")
        else:
            payload = {
                "PitchID": int(current_pid),
                "RunnerID": player_map[runner],
                "StartBase": int(start_base),
                "EndBase": None if end_base == 0 else int(end_base),
                "EventType": event_type,
                "OutRecorded": (out_recorded == "Yes")
            }
            try:
                resp = supabase.table("RunnerEvents").insert(payload).execute()
                if resp.data:
                    arrow = f"{start_base}→{end_base if end_base!=0 else '-'}"
                    add_to_summary(f"Runner {runner}: {event_type} | {arrow} | Out={payload['OutRecorded']}")
                    st.success("Runner event saved.")
                else:
                    st.error("Failed to save runner event.")
            except Exception as e:
                st.error(f"Insert failed: {e}")

# ---------------------------------------------------------
# Running Summary
# ---------------------------------------------------------
st.markdown("---")
st.subheader("Running Summary (this session)")
if st.session_state["event_log"]:
    for line in st.session_state["event_log"][:50]:
        st.write("• " + line)
else:
    st.caption("No events yet. Enter pitches or runner events to see them here.")

# Footer
st.caption(f"Game ID: {st.session_state.get('selected_game_id')} | AtBat ID: {st.session_state.get('current_atbat_id')} | Count: {st.session_state['balls']}-{st.session_state['strikes']}")

import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Tracker")

# ---------------------------------------------------------
# Supabase connection
# ---------------------------------------------------------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def ensure_player(name, team=None, throws=None, bats=None):
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

def create_atbat(game_id, batter_id, pitcher_id, inning):
    payload = {"GameID": int(game_id), "BatterID": int(batter_id), "PitcherID": int(pitcher_id), "Inning": int(inning)}
    resp = supabase.table("AtBats").insert(payload).execute()
    return resp.data[0]["AtBatID"] if resp.data else None

def next_pitch_numbers_for(atbat_id):
    """Return (next global PitchNo, next PitchOfAB) with safe defaults."""
    try:
        r1 = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
        last_global = r1.data[0]["PitchNo"] if r1.data and r1.data[0]["PitchNo"] is not None else 0
    except Exception:
        last_global = 0

    try:
        r2 = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
        last_poab = r2.data[0]["PitchOfAB"] if r2.data and r2.data[0]["PitchOfAB"] is not None else 0
    except Exception:
        last_poab = 0

    return (int(last_global) + 1, int(last_poab) + 1)

def compute_wel(balls, strikes):
    t = (balls, strikes)
    if t in [(0,0),(0,1),(1,0),(1,1)]: return "E"
    if t in [(0,2),(1,2)]: return "W"
    if t in [(2,0),(2,1)]: return "L"
    return None

def insert_pitch(atbat_id, pitch_no, pitch_of_ab, pitch_type, velocity, zone, pitch_called, balls, strikes, wel, tagged, hitdir, kpi):
    payload = {
        "AtBatID": int(atbat_id),
        "PitchNo": int(pitch_no),
        "PitchOfAB": int(pitch_of_ab),
        "PitchType": pitch_type,
        "Velocity": None if not velocity else float(velocity),
        "Zone": None if not zone else int(zone),
        "PitchCalled": pitch_called,
        "WEL": wel,
        "Balls": int(balls),
        "Strikes": int(strikes),
        "TaggedHit": tagged,
        "HitDirection": hitdir,
        "KPI": kpi
    }
    return supabase.table("Pitches").insert(payload).execute()

def update_atbat(atbat_id, updates: dict):
    """Update the AtBats table for the given AtBatID."""
    try:
        resp = (
            supabase
            .table("AtBats")
            .update(updates)
            .eq("AtBatID", atbat_id)
            .execute()
        )
        return resp
    except Exception as e:
        st.error(f"Failed to update AtBat {atbat_id}: {e}")
        return None

def add_to_summary(line: str):
    st.session_state["event_log"].insert(0, line)

# ---------------------------------------------------------
# Session defaults
# ---------------------------------------------------------
defaults = {
    "lineup": [],
    "pitchers": [],
    "selected_game_id": None,
    "current_batter_id": None,
    "current_pitcher_id": None,
    "current_atbat_id": None,
    "balls": 0,
    "strikes": 0,
    "pitch_history": [],
    "last_pitch_summary": None,
    "last_saved_pitch_id": None,
    "event_log": []
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------
# Initialize pitch quick-entry defaults
# ---------------------------------------------------------
for key, default in {
    "quick_pitch_type": None,
    "quick_pitch_called": None,
    "quick_vel": 0.0,
    "quick_zone": "None"
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------
# Ensure a game is active
# ---------------------------------------------------------
if not st.session_state.get("selected_game_id"):
    st.warning("Please go to the Game Setup page first to create and start a game.")
    st.stop()

st.title("Pitch Tracker")

# ---------------------------------------------------------
# 1 — Select AtBat
# ---------------------------------------------------------
st.header("1 — Select AtBat")
col1, col2, col3 = st.columns([3,3,2])

with col1:
    lineup_names = [x["Name"] for x in st.session_state["lineup"]]
    batter_choice = st.selectbox("Select Batter", ["-- Select --"] + lineup_names)
    if batter_choice != "-- Select --":
        sel = next((x for x in st.session_state["lineup"] if x["Name"] == batter_choice), None)
        if sel:
            st.session_state["current_batter_id"] = sel["PlayerID"]
            st.write(f"Selected batter: {sel['Name']} (slot {sel['Order']})")

with col2:
    pitch_names = [x["Name"] for x in st.session_state["pitchers"]]
    pitcher_choice = st.selectbox("Select Pitcher", ["-- Select --"] + pitch_names)
    if pitcher_choice != "-- Select --":
        sp = next((x for x in st.session_state["pitchers"] if x["Name"] == pitcher_choice), None)
        if sp:
            st.session_state["current_pitcher_id"] = sp["PlayerID"]
            st.write(f"Selected pitcher: {sp['Name']}")

with col3:
    inning_val = st.number_input("Inning", min_value=1, value=1)
    if st.button("Start AtBat"):
        if not st.session_state["current_batter_id"] or not st.session_state["current_pitcher_id"]:
            st.error("Select batter and pitcher first.")
        else:
            atbat_id = create_atbat(
                st.session_state["selected_game_id"],
                st.session_state["current_batter_id"],
                st.session_state["current_pitcher_id"],
                inning_val
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
                st.error("Failed to create AtBat.")

# ---------------------------------------------------------
# 2 — Pitch Entry (Simplified Unified Form)
# ---------------------------------------------------------
st.header("2 — Pitch Entry")

if not st.session_state["current_atbat_id"]:
    st.info("Start an AtBat to enter pitches.")
else:
    atbat_id = st.session_state["current_atbat_id"]

    # Fetch next pitch numbers dynamically
    def refresh_pitch_numbers():
        pno, poab = next_pitch_numbers_for(atbat_id)
        st.session_state["next_pitch_no"] = pno
        st.session_state["next_pitch_of_ab"] = poab

    if "next_pitch_no" not in st.session_state or "next_pitch_of_ab" not in st.session_state:
        refresh_pitch_numbers()

    st.write(f"Next PitchNo: **{st.session_state['next_pitch_no']}** — PitchOfAB: **{st.session_state['next_pitch_of_ab']}**")
    st.write(f"Count: **{st.session_state['balls']}-{st.session_state['strikes']}**")

    # Display last pitch info
    if st.session_state["last_pitch_summary"]:
        st.info("Last pitch: " + st.session_state["last_pitch_summary"])
        if st.button("Undo Last Pitch"):
            if st.session_state["pitch_history"]:
                last_pid = st.session_state["pitch_history"].pop()
                try:
                    supabase.table("Pitches").delete().eq("PitchID", last_pid).execute()

                    # Recalculate balls/strikes from remaining pitches
                    rec = (
                        supabase.table("Pitches")
                        .select("Balls, Strikes")
                        .eq("AtBatID", atbat_id)
                        .order("PitchOfAB", desc=True)
                        .limit(1)
                        .execute()
                        .data
                        or []
                    )
                    if rec:
                        st.session_state["balls"] = rec[0].get("Balls", 0)
                        st.session_state["strikes"] = rec[0].get("Strikes", 0)
                    else:
                        st.session_state["balls"] = 0
                        st.session_state["strikes"] = 0

                    # Clear last pitch info and refresh pitch number display
                    st.session_state["last_pitch_summary"] = None
                    refresh_pitch_numbers()
                    st.success("Undo successful — pitch removed and count updated.")
                except Exception as e:
                    st.error("Undo failed: " + str(e))
            else:
                st.warning("No pitch to undo.")

    # --- Pitch Type Section ---
    st.subheader("Pitch Type")

# 💅 Custom CSS to make buttons wider and prevent word wrapping
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"] div[data-testid="column"] button {
        width: 100%;
        white-space: nowrap !important;
        overflow: hidden;
        text-overflow: ellipsis;
        font-weight: 600;
        border-radius: 8px;
          padding: 0.6em 0.2em;
    }
    </style>
    """, unsafe_allow_html=True)

# Helper function to display buttons in a grid layout
    def button_grid(labels, buttons_per_row=4, prefix="btn"):
        rows = [labels[i:i + buttons_per_row] for i in range(0, len(labels), buttons_per_row)]
        for row in rows:
            cols = st.columns(len(row))
            for i, label in enumerate(row):
                if cols[i].button(label, key=f"{prefix}_{label}"):
                    return label
        return None

# Use the grid helper
    pitch_types = ["Fastball", "Slider", "Curveball", "Changeup", "Cutter", "Splitter", "Other"]
    selected_pitch = button_grid(pitch_types, buttons_per_row=4, prefix="pt")

    if selected_pitch:
        st.session_state["quick_pitch_type"] = selected_pitch

    st.caption(f"Selected type: {st.session_state.get('quick_pitch_type', '—')}")

    # --- Pitch Called Buttons ---
    st.subheader("Pitch Result")
    call_options = ["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"]
    pc_cols = st.columns(len(call_options))
    for i, c in enumerate(call_options):
        if pc_cols[i].button(c, key=f"pc_{c}"):
            st.session_state["quick_pitch_called"] = c
    st.caption(f"Selected called: {st.session_state['quick_pitch_called'] or '—'}")

    # --- Additional Info Section ---
    st.subheader("Additional Info")
    colA, colB, colC, colD = st.columns(4)
    with colA:
        zone_val = st.selectbox("Zone (optional)", ["None"] + [str(i) for i in range(1, 15)],
                                key="quick_zone_sel", index=(int(st.session_state.get("quick_zone", "0")) if st.session_state.get("quick_zone") not in [None, "None"] else 0))
    with colB:
        vel_val = st.number_input("Velocity (mph, optional)", min_value=0.0, step=0.1,
                                  value=float(st.session_state.get("quick_vel", 0.0)), key="quick_vel_inp")
    with colC:
        tagged_val = st.selectbox("Tagged Hit", ["None", "Bunt", "Flyball", "Groundball", "Linedrive"], key="quick_tagged_sel")
    with colD:
        hitdir_val = st.selectbox("Hit Direction", ["None", "3-4 Hole", "5-6 Hole", "Catcher", "Center Field",
                                                    "First Base", "Left Center", "Left Field", "Middle", "Pitcher",
                                                    "Right Center", "Right Field", "Second Base", "Short Stop", "Third Base"],
                                  key="quick_hitdir_sel")

    kpi_val = st.text_input("KPI / Notes (optional)", key="quick_kpi_inp")

    # --- Submit Pitch ---
    if st.button("Submit Pitch"):
        if not st.session_state.get("quick_pitch_type") or not st.session_state.get("quick_pitch_called"):
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
            zone_num = None if zone_val == "None" else int(zone_val)
            tagged_hit = None if tagged_val == "None" else tagged_val
            hit_dir = None if hitdir_val == "None" else hitdir_val

            # Insert pitch into Supabase
            r = insert_pitch(
                atbat_id=atbat_id,
                pitch_no=st.session_state["next_pitch_no"],
                pitch_of_ab=st.session_state["next_pitch_of_ab"],
                pitch_type=st.session_state["quick_pitch_type"],
                velocity=vel_val,
                zone=zone_num,
                pitch_called=called,
                balls=st.session_state["balls"],
                strikes=st.session_state["strikes"],
                wel=wel,
                tagged=tagged_hit,
                hitdir=hit_dir,
                kpi=kpi_val
            )

            if r.data:
                pid = r.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_saved_pitch_id"] = pid
                batter_name = next((x["Name"] for x in st.session_state["lineup"]
                                    if x["PlayerID"] == st.session_state["current_batter_id"]), "Unknown")
                summary_line = f"{batter_name}: {st.session_state['quick_pitch_type']} {vel_val} — {called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.session_state["last_pitch_summary"] = summary_line
                add_to_summary(f"Batter {batter_name} | Pitch {st.session_state['next_pitch_no']}: {st.session_state['quick_pitch_type']} — {called} | {st.session_state['balls']}-{st.session_state['strikes']}")

                # Reset selections and update next pitch number
                st.session_state["quick_pitch_type"] = None
                st.session_state["quick_pitch_called"] = None
                st.session_state["quick_zone"] = "None"
                st.session_state["quick_vel"] = 0.0

                # Reset widget values safely (use local state updates)
                for key in ["quick_tagged_sel", "quick_hitdir_sel", "quick_kpi_inp"]:
                    if key in st.session_state:
                        del st.session_state[key]

                refresh_pitch_numbers()
                st.success("Pitch saved.")

                else:
                    st.error("Pitch not saved. Check DB schema.")


# ---------------------------------------------------------
# 3 — Finish AtBat (result + LeadOffOn here)
# ---------------------------------------------------------
st.header("3 — Finish AtBat")
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
# 4 — Runner Events (attach to last pitch)
# ---------------------------------------------------------
st.header("4 — Runner Events")
current_pid = st.session_state.get("last_saved_pitch_id") or (
    st.session_state["pitch_history"][-1] if st.session_state["pitch_history"] else None
)

if not current_pid:
    st.info("Log a pitch first to attach runner events.")
else:
    st.write(f"Attaching events to PitchID: {current_pid}")
    try:
        players = supabase.table("Players").select("PlayerID, Name").order("Name", desc=False).execute().data or []
    except Exception as e:
        st.error(f"Could not load players: {e}")
        players = []

    if players:
        player_map = {p["Name"]: p["PlayerID"] for p in players}

        runner = st.selectbox("Runner", ["-- Select --"] + list(player_map.keys()))
        start_base = st.selectbox("Start Base", [1, 2, 3, 4])
        end_base = st.selectbox("End Base (0=None)", [0, 1, 2, 3, 4], format_func=lambda x: "None" if x == 0 else str(x))
        event_type = st.selectbox("Event Type", ["Stolen Base", "Caught Stealing", "Pickoff", "Out on Play", "Advanced on Hit", "Other"])
        out_recorded = st.selectbox("Out Recorded", ["No", "Yes"])

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
                    "OutRecorded": (out_recorded == "Yes"),
                }
                try:
                    resp = supabase.table("RunnerEvents").insert(payload).execute()
                    if resp.data:
                        arrow = f"{start_base}→{end_base if end_base != 0 else '-'}"
                        add_to_summary(f"Runner {runner}: {event_type} | {arrow} | Out={payload['OutRecorded']}")
                        st.success("Runner event saved.")
                    else:
                        st.error("Failed to save runner event.")
                except Exception as e:
                    st.error(f"Insert failed: {e}")

# ---------------------------------------------------------
# 5 — Running Summary
# ---------------------------------------------------------
st.markdown("---")
st.subheader("Running Summary")
if st.session_state["event_log"]:
    for line in st.session_state["event_log"]:
        st.write("• " + line)
else:
    st.caption("No events yet. Pitch, record a runner event, or finish an at-bat to see entries here.")

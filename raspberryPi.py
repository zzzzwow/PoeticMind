from flask import Flask, render_template, request, jsonify
import serial
import threading
import time
from openai import OpenAI
from datetime import datetime
import json
from collections import deque

# Please replace it with your own OpenAI API key
client = OpenAI(api_key="change to your own API key")

app = Flask(__name__)
ser = None
rMSSD_values = []
start_collecting = False
initial_rMSSD = None

eda_deltas = deque(maxlen=8)
eda_baseline_seen = False
eda_before = None
eda_after = None

printing_done = False

def read_serial_data():
    global rMSSD_values, ser, start_collecting, printing_done
    global eda_deltas, eda_baseline_seen
    print("🔁 Serial reader thread started...")
    while True:
        if ser and ser.in_waiting:
            try:
                raw = ser.readline().decode('utf-8', errors='ignore').strip()
                if not raw:
                    time.sleep(0.005)
                    continue

                if raw.startswith("rMSSD:"):
                    try:
                        value = float(raw.split(":")[1].strip())
                        if start_collecting:
                            rMSSD_values.append(value)
                            print(f"📥 Collected rMSSD (legacy): {value}")
                    except:
                        print("[Arduino] (legacy parse fail) →", raw)
                    continue

                if raw.startswith("{") and raw.endswith("}"):
                    try:
                        obj = json.loads(raw)
                        typ = obj.get("type", "").upper()
                        if typ == "HRV":
                            val = float(obj.get("rMSSD_ms", 0))
                            if start_collecting:
                                rMSSD_values.append(val)
                                print(f"📥 Collected rMSSD: {val}")
                        elif typ == "EDA_BASELINE":
                            eda_baseline_seen = True
                            print(f"📏 EDA baseline acknowledged: {obj.get('baseline')}")
                        elif typ == "EDA":
                            d = float(obj.get("delta", 0.0))
                            eda_deltas.append(d)
                            print(f"📥 ΔEDA epoch received: {d:.6f}")
                        else:
                            print("[Arduino JSON] →", obj)
                        continue
                    except Exception as je:
                        print(f"❌ JSON parse error: {je} | raw={raw}")

                if "printing finished" in raw.lower():
                    printing_done = True
                    print("✅ Printing completed.")
                else:
                    print("[Arduino] →", raw)
            except Exception as e:
                print(f"❌ Serial error: {e}")
        time.sleep(0.01)

def build_prompt(answers, delta_rmssd, dd_eda):
    import random

    poetic_forms = [
        "five-line poem following the AABBA rhyme scheme",
        "five-line poem following the ABABA rhyme scheme",
        "free verse poem with no specific rhyme or meter (maximum 6 lines)",
        "four-line poem in ballad meter, using ABCB rhyme scheme",
        "four-line poem using an ABAB rhyme scheme",
        "four-line poem with internal rhyme—include at least one rhyme inside each line. Use a light, conversational tone that sounds rhythmic when read aloud.",
        "haiku-style poem with nature imagery (3 lines only)",
        "sonnet-style poem with emotional depth (maximum 6 lines, condensed form)",
        "prose poem with flowing narrative (maximum 3 lines)",
        "concrete poem that plays with visual arrangement (maximum 6 lines)",
        "limerick with humor and wit (5 lines only)",
        "villanelle with repeating lines (maximum 6 lines, condensed form)"
    ]
    poetic_form = random.choice(poetic_forms)

    # Extended Intonation Mapping (Q1)
    q1_map = {
        'A': "Let the tone remain gentle and undisturbed.",
        'B': "Let the poem move with joy and vibrant rhythm, as if celebrating alongside the reader.",
        'C': "Let the lines offer quiet reassurance and affirm the reader's worth. And Let the voice be intimate and confessional.",
        'D': "Let the poem wander with curiosity, inviting the reader to explore something unknown.",
    }

    # Q4: Color Mapping - Language Style Control
    q4_map = {
        'A': "Let the language carry the warmth of existence, using soft, gentle tones that embrace the reader.",
        'B': "Use language that pauses naturally, doesn't rush to conclusions, embraces ambiguity, and lets silence itself create meaning.",
        'C': "Employ vivid imagery and sharp, unexpected turns that give the poem its pulse and energy.",
        'D': "Use smooth, flowing sentences that move with a calm, measured rhythm."
    }

    # Q5: Story Type Mapping - Emotional Expression Methods
    q5_map = {
        'A': "Describe memory fragments triggered by scents, familiar shapes, or song melodies that create resonance with the reader.",
        'B': "Focus on one specific moment, event, or achievement, using beautiful, detailed description of a concrete image.",
        'C': "Let emotions unfold in layers, allowing unexpected changes in grammar and tone, using symbolic language.",
        'D': "Use powerful verbs to create a poem full of exploration and vitality, flowing freely with imagination and fictional elements."
    }

    # Poetry category mapping based on Q2 and Q3
    style_map = {
        ('A', 'A'): ('Romanticism', 'A Romantic poet who celebrates inner peace and contemplative moments'),
        ('A', 'B'): ('Pastoral', 'A Pastoral poet who finds joy in simplicity and beauty'),
        ('A', 'C'): ('Imagism', 'An Imagist poet who captures precise moments and sensory details'),
        ('A', 'D'): ('Sublime Romanticism', 'A Romantic poet who explores the sublime and powerful emotions'),
        ('B', 'A'): ('Modernism', 'A Modernist poet who captures complexity and introspective depth'),
        ('B', 'B'): ('Postmodernism', 'A Postmodern poet who celebrates energy and cultural diversity'),
        ('B', 'C'): ('Urban Imagism', 'An Imagist poet who finds beauty in precise details and rhythms'),
        ('B', 'D'): ('Expressionism', 'An Expressionist poet who captures intensity and emotional drama'),
        ('C', 'A'): ('Symbolism', 'A Symbolist poet who explores mystery and spiritual depth'),
        ('C', 'B'): ('Surrealism', 'A Surrealist poet who blends reality with dreamlike imagery'),
        ('C', 'C'): ('Impressionism', 'An Impressionist poet who captures mood and atmospheric effects'),
        ('C', 'D'): ('Gothic Romanticism', 'A Gothic Romantic poet who explores darkness and emotional intensity'),
        ('D', 'A'): ('Sublime Aesthetics', 'A poet who explores the sublime and philosophical depth'),
        ('D', 'B'): ('Heroic Poetry', 'A heroic poet who celebrates strength and triumph over challenges'),
        ('D', 'C'): ('Classicism', 'A Classical poet who seeks harmony and balance in form and content'),
        ('D', 'D'): ('Tragic Aesthetics', 'A poet who explores power, conflict, and dramatic tension')
    }

    style_info = style_map.get((answers.get("Q2"), answers.get("Q3")), ("Romanticism", "A Romantic poet who celebrates nature and inner peace"))
    style, style_description = style_info

    # Randomly select topic categories to enforce diversity
    import random as _random
    theme_categories = [
        "technology and digital life",
        "domestic scenes and home life",
        "work and professional environments",
        "travel and transportation",
        "food and culinary experiences",
        "art and creative expression",
        "science and discovery",
        "historical moments and memories",
        "social interactions and relationships",
        "abstract concepts and philosophy",
        "sports and physical activities",
        "education and learning",
        "commerce and economic life",
        "entertainment and media",
        "health and wellness",
        "politics and social issues",
        "aging and the passage of time",
        "childhood memories and innocence",
        "loneliness and human connection",
        "personal growth and transformation",
        "loss and the process of healing",
        "the search for meaning and purpose",
        "cultural identity and belonging",
        "the beauty of ordinary moments"
    ]
    selected_theme = _random.choice(theme_categories)

    base = f"Please write a {poetic_form} in English about {selected_theme}. Use any narrative perspective (first person, second person, third person, or no specific person) that best serves the poem's emotional depth."

    if delta_rmssd >= 0:
        mood_options = [
            "The poem should be gentle and uplifting.",
            "The poem should convey hope and renewal.",
            "The poem should celebrate life and vitality.",
            "The poem should inspire wonder and gratitude."
        ]
        mood = _random.choice(mood_options)
    else:
        mood_options = [
            "The poem should be comforting and emotionally warm.",
            "The poem should offer solace and understanding.",
            "The poem should provide gentle reassurance.",
            "The poem should embrace vulnerability with tenderness."
        ]
        mood = _random.choice(mood_options)

    if dd_eda is None:
        pacing = "Keep a balanced pacing—neither rushed nor overly slow."
    else:
        if dd_eda > 0.0:
            pacing = "Increase kinetic energy: use quicker turns, slightly shorter lines, and a feeling of rising arousal."
        elif dd_eda < 0.0:
            pacing = "Settle the arousal: use calmer movement, slightly longer lines, and a measured, breathable rhythm."
        else:
            pacing = "Keep a balanced pacing—neither rushed nor overly slow."

    prompt_parts = [
        base,
        "IMPORTANT: The poem must be no more than 6 lines total. Keep it concise and impactful.",
        mood,
        pacing,
        q1_map.get(answers.get("Q1"), ""),
        f"Write in the spirit of {style_description}, drawing inspiration from the {style} tradition.",
        q4_map.get(answers.get("Q4"), ""),
        q5_map.get(answers.get("Q5"), ""),
        "Make the poem unique and avoid common poetic clichés. Use fresh, original language.",
        "CRITICAL: The user's questionnaire answers only indicate their emotional state and preferred writing style. Do NOT let these answers limit your choice of themes, settings, or imagery. Be completely creative and imaginative in your subject matter. Avoid any predictable or stereotypical associations with the questionnaire themes. Choose unexpected, diverse, and original content while maintaining the requested emotional tone and writing style.",
        "IMPORTANT: Select a completely random and unexpected theme for this poem. Consider urban life, technology, human relationships, abstract concepts, historical events, scientific phenomena, or any other diverse subject matter. Avoid any connection to the questionnaire themes.",
        "CRITICAL: Each poem should be completely unique. Avoid repeating any words, phrases, objects, colors, or imagery that might have been used in previous poems. Choose fresh vocabulary and imagery for every new poem. Make each poem feel like it was written by a different person about a completely different subject.",
        "IMPORTANT: Create a poem with emotional depth and resonance. Explore universal human experiences, complex emotions, or profound insights. The poem should move the reader emotionally and offer meaningful reflection. Consider themes of vulnerability, transformation, connection, loss, hope, or the human condition."
    ]
    return "\n\n".join(prompt_parts)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    """Start collecting the baseline: 3 seconds rMSSD baseline + the first ΔEDA epoch (you need to wait for up to 4 seconds more)"""
    global rMSSD_values, start_collecting, initial_rMSSD
    global eda_before, eda_deltas, eda_baseline_seen

    print("🟢 User pressed YES – starting baseline collection")
    rMSSD_values = []
    eda_deltas.clear()
    eda_before = None
    eda_baseline_seen = False

    # 1) Start the 3-second rMSSD collection
    start_collecting = True
    time.sleep(3.0)  # 3s baseline window
    if rMSSD_values:
        initial_rMSSD = sum(rMSSD_values) / len(rMSSD_values)
        print(f"📊 Baseline rMSSD = {initial_rMSSD:.2f}")
    else:
        print("⚠️ No rMSSD collected in baseline window.")
        initial_rMSSD = 0.0

    # 2) Wait for the first ΔEDA (Arduino needs to go through a 3-second baseline before starting to output ΔEDA).
    t0 = time.time()
    got_eda = False
    while time.time() - t0 < 4.0:
        if len(eda_deltas) > 0:
            eda_before = eda_deltas[-1]
            got_eda = True
            break
        time.sleep(0.05)
    if got_eda:
        print(f"📏 ΔEDA_before (epoch) = {eda_before:.6f}")
    else:
        print("⚠️ Did not receive ΔEDA_before in time.")
        eda_before = 0.0

    rMSSD_values = []
    return '', 204

@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    """Submit the questionnaire: Calculate ΔrMSSD; Wait for a ΔEDA epoch and calculate ΔΔEDA; Then call GPT to generate the poem."""
    global rMSSD_values, initial_rMSSD, start_collecting, printing_done
    global eda_before, eda_after, eda_deltas

    printing_done = False
    data = request.get_json()
    answers = data.get('answers', {})
    print(f"📥 Received answers: {answers}")

    # End the rMSSD collection window (treat the RMSSDS collected during the questionnaire stage as final)
    final_rMSSD = sum(rMSSD_values) / len(rMSSD_values) if rMSSD_values else 0.0
    delta_rmssd = final_rMSSD - (initial_rMSSD or 0.0)
    print(f"📈 ΔrMSSD = {final_rMSSD:.2f} - {initial_rMSSD or 0.0:.2f} = {delta_rmssd:.2f}")
    start_collecting = False
    rMSSD_values = []

    # Wait for a ΔEDA epoch as after (up to 4 seconds)
    t0 = time.time()
    got_eda_after = False
    eda_after = None
    while time.time() - t0 < 4.0:
        if len(eda_deltas) > 0:
            eda_after = eda_deltas[-1]
            got_eda_after = True
            break
        time.sleep(0.05)
    if got_eda_after:
        print(f"📏 ΔEDA_after (epoch) = {eda_after:.6f}")
    else:
        print("⚠️ Did not receive ΔEDA_after in time.")
        eda_after = 0.0

    # calculating ΔΔEDA
    dd_eda = None
    if eda_before is not None and eda_after is not None:
        dd_eda = eda_after - eda_before
        print(f"📊 ΔΔEDA = {eda_after:.6f} - {eda_before:.6f} = {dd_eda:.6f}")
    else:
        print("⚠️ ΔΔEDA not available; proceeding without pacing control.")

    prompt = build_prompt(answers, delta_rmssd, dd_eda)
    print("📜 Prompt to GPT:\n", prompt)

    try:
        print("🤖 Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=200,
            top_p=0.9,
            frequency_penalty=0.5,
            presence_penalty=0.3
        )
        poem = response.choices[0].message.content.strip()
        print("📝 Poem generated:\n", poem)

        # Send the current time + the text of the poem to Arduino
        current_time = datetime.now().strftime("%H:%M   %d/%m/%Y")
        if ser:
            try:
                print("📤 [Pi] Sending poem and timestamp to Arduino...")
                ser.write((current_time + "\n").encode("ascii", errors="ignore"))
                time.sleep(0.2)
                for line in poem.split("\n"):
                    ser.write((line + "\n").encode("ascii", errors="ignore"))
                    time.sleep(0.2)
                print("✅ [Pi] already sent poetry text")
            except Exception as e:
                print("❌ [Pi] Failed to send poem:", e)
        else:
            print("⚠️ [Pi] Serial port not available.")

        return jsonify({'poem': poem})
    except Exception as e:
        print("❌ GPT error:", e)
        return jsonify({'poem': "Sorry, there was an error generating your poem."})

@app.route('/status')
def status():
    return jsonify({'printing_done': printing_done})

if __name__ == '__main__':
    import serial.tools.list_ports
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if 'ttyACM' in p.device or 'USB' in p.device:
            try:
                ser = serial.Serial(p.device, 9600, timeout=1)
                print(f"🔌 Connected to {p.device}")
                break
            except Exception as e:
                print(f"⚠️ Failed to connect to {p.device}: {e}")

    if ser:
        time.sleep(2)
        print("⏳ Waiting for Arduino to be ready...")
        while ser.in_waiting:
            ser.readline()
        print("✅ Ready.")
        thread = threading.Thread(target=read_serial_data)
        thread.daemon = True
        thread.start()
    else:
        print("❌ No serial device found.")

    app.run(host='0.0.0.0', port=5000, debug=True)

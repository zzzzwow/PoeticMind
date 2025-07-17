from flask import Flask, render_template, request, jsonify
import serial
import threading
import time
from openai import OpenAI
from datetime import datetime

# 请替换为你自己的 OpenAI API 密钥
client = OpenAI(api_key="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")

app = Flask(__name__)
ser = None
rMSSD_values = []
start_collecting = False
initial_rMSSD = None
printing_done = False  # 打印完成标志

def read_serial_data():
    global rMSSD_values, ser, start_collecting, printing_done
    print("🔁 Serial reader thread started...")
    while True:
        if ser and ser.in_waiting:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith("rMSSD:"):
                    value = float(line.split(":")[1].strip())
                    if start_collecting:
                        rMSSD_values.append(value)
                        print(f"📥 Collected rMSSD: {value}")
                elif "printing finished" in line.lower():
                    printing_done = True
                    print("✅ Printing completed.")
                else:
                    print("[Arduino] →", line)
            except Exception as e:
                print(f"❌ Serial error: {e}")
        time.sleep(0.01)

def build_prompt(answers, delta):
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

    # 扩展语调映射
    q1_map = {
        'A': "Let the tone remain gentle and undisturbed.",
        'B': "Let the poem move with joy and vibrant rhythm, as if celebrating alongside the reader.",
        'C': "Let the lines offer quiet reassurance and affirm the reader's worth. And Let the voice be intimate and confessional.",
        'D': "Let the poem wander with curiosity, inviting the reader to explore something unknown.",
        #'E': "Let the tone be contemplative and philosophical.",
        #'H': "Let the poem dance with playful energy and spontaneity."
    }

    # 第四题：颜色映射 - 语言风格控制
    q4_map = {
        'A': "Let the language carry the warmth of existence, using soft, gentle tones that embrace the reader.",
        'B': "Use language that pauses naturally, doesn't rush to conclusions, embraces ambiguity, and lets silence itself create meaning.",
        'C': "Employ vivid imagery and sharp, unexpected turns that give the poem its pulse and energy.",
        'D': "Use smooth, flowing sentences that move with a calm, measured rhythm."
    }

    # 第五题：故事类型映射 - 情感表达方式
    q5_map = {
        'A': "Describe memory fragments triggered by scents, familiar shapes, or song melodies that create resonance with the reader.",
        'B': "Focus on one specific moment, event, or achievement, using beautiful, detailed description of a concrete image.",
        'C': "Let emotions unfold in layers, allowing unexpected changes in grammar and tone, using symbolic language.",
        'D': "Use powerful verbs to create a poem full of exploration and vitality, flowing freely with imagination and fictional elements."
    }

    # 基于Q2和Q3的诗歌派别映射 (Q2: 心境景观, Q3: 情感声音) - 仅影响风格，不限制内容
    style_map = {
        # 宁静森林 + 雨声 = 自然主义/浪漫主义
        ('A', 'A'): ('Romanticism', 'A Romantic poet who celebrates inner peace and contemplative moments'),
        
        # 宁静森林 + 欢快旋律 = 田园诗/牧歌风格
        ('A', 'B'): ('Pastoral', 'A Pastoral poet who finds joy in simplicity and beauty'),
        
        # 宁静森林 + 城市低语 = 现代主义/意象派
        ('A', 'C'): ('Imagism', 'An Imagist poet who captures precise moments and sensory details'),
        
        # 宁静森林 + 雷声 = 崇高美学/浪漫主义
        ('A', 'D'): ('Sublime Romanticism', 'A Romantic poet who explores the sublime and powerful emotions'),
        
        # 繁华城市 + 雨声 = 现代主义/都市诗
        ('B', 'A'): ('Modernism', 'A Modernist poet who captures complexity and introspective depth'),
        
        # 繁华城市 + 欢快旋律 = 后现代主义/实验诗
        ('B', 'B'): ('Postmodernism', 'A Postmodern poet who celebrates energy and cultural diversity'),
        
        # 繁华城市 + 城市低语 = 意象派/都市意象
        ('B', 'C'): ('Urban Imagism', 'An Imagist poet who finds beauty in precise details and rhythms'),
        
        # 繁华城市 + 雷声 = 表现主义/都市戏剧
        ('B', 'D'): ('Expressionism', 'An Expressionist poet who captures intensity and emotional drama'),
        
        # 雾霭海岸 + 雨声 = 象征主义/神秘主义
        ('C', 'A'): ('Symbolism', 'A Symbolist poet who explores mystery and spiritual depth'),
        
        # 雾霭海岸 + 欢快旋律 = 超现实主义/梦幻诗
        ('C', 'B'): ('Surrealism', 'A Surrealist poet who blends reality with dreamlike imagery'),
        
        # 雾霭海岸 + 城市低语 = 印象主义/氛围诗
        ('C', 'C'): ('Impressionism', 'An Impressionist poet who captures mood and atmospheric effects'),
        
        # 雾霭海岸 + 雷声 = 哥特浪漫主义/黑暗美学
        ('C', 'D'): ('Gothic Romanticism', 'A Gothic Romantic poet who explores darkness and emotional intensity'),
        
        # 巍峨山景 + 雨声 = 崇高美学/自然哲学
        ('D', 'A'): ('Sublime Aesthetics', 'A poet who explores the sublime and philosophical depth'),
        
        # 巍峨山景 + 欢快旋律 = 英雄主义/史诗风格
        ('D', 'B'): ('Heroic Poetry', 'A heroic poet who celebrates strength and triumph over challenges'),
        
        # 巍峨山景 + 城市低语 = 古典主义/平衡美学
        ('D', 'C'): ('Classicism', 'A Classical poet who seeks harmony and balance in form and content'),
        
        # 巍峨山景 + 雷声 = 悲剧美学/力量诗
        ('D', 'D'): ('Tragic Aesthetics', 'A poet who explores power, conflict, and dramatic tension')
    }

    # 基于Q2和Q3选择诗歌派别
    style_info = style_map.get((answers.get("Q2"), answers.get("Q3")), ("Romanticism", "A Romantic poet who celebrates nature and inner peace"))
    style, style_description = style_info



    # 随机选择主题类别来强制多样性
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
    selected_theme = random.choice(theme_categories)
    
    base = f"Please write a {poetic_form} in English about {selected_theme}. Use any narrative perspective (first person, second person, third person, or no specific person) that best serves the poem's emotional depth."
    
    # 扩展情绪基调
    if delta >= 0:
        mood_options = [
            "The poem should be gentle and uplifting.",
            "The poem should convey hope and renewal.",
            "The poem should celebrate life and vitality.",
            "The poem should inspire wonder and gratitude."
        ]
        mood = random.choice(mood_options)
    else:
        mood_options = [
            "The poem should be comforting and emotionally warm.",
            "The poem should offer solace and understanding.",
            "The poem should provide gentle reassurance.",
            "The poem should embrace vulnerability with tenderness."
        ]
        mood = random.choice(mood_options)

    # 构建更丰富的prompt
    prompt_parts = [
        base,
        "IMPORTANT: The poem must be no more than 6 lines total. Keep it concise and impactful.",
        mood,
        q1_map.get(answers.get("Q1"), ""),
        f"Write in the spirit of {style_description}, drawing inspiration from the {style} tradition.",
        q4_map.get(answers.get("Q4"), ""),
        q5_map.get(answers.get("Q5"), ""),
        f"Make the poem unique and avoid common poetic clichés. Use fresh, original language.",
        f"CRITICAL: The user's questionnaire answers only indicate their emotional state and preferred writing style. Do NOT let these answers limit your choice of themes, settings, or imagery. Be completely creative and imaginative in your subject matter. Avoid any predictable or stereotypical associations with the questionnaire themes. Choose unexpected, diverse, and original content while maintaining the requested emotional tone and writing style.",
        f"IMPORTANT: Select a completely random and unexpected theme for this poem. Consider urban life, technology, human relationships, abstract concepts, historical events, scientific phenomena, or any other diverse subject matter. Avoid any connection to the questionnaire themes.",
        f"CRITICAL: Each poem should be completely unique. Avoid repeating any words, phrases, objects, colors, or imagery that might have been used in previous poems. Choose fresh vocabulary and imagery for every new poem. Make each poem feel like it was written by a different person about a completely different subject.",
        f"IMPORTANT: Create a poem with emotional depth and resonance. Explore universal human experiences, complex emotions, or profound insights. The poem should move the reader emotionally and offer meaningful reflection. Consider themes of vulnerability, transformation, connection, loss, hope, or the human condition. Make the poem genuinely touching and thought-provoking."
    ]
    
    return "\n\n".join(prompt_parts)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    global rMSSD_values, start_collecting, initial_rMSSD
    print("🟢 User pressed YES – starting baseline collection")
    rMSSD_values = []
    start_collecting = True
    time.sleep(3)
    if rMSSD_values:
        initial_rMSSD = sum(rMSSD_values) / len(rMSSD_values)
        print(f"📊 Baseline rMSSD = {initial_rMSSD:.2f}")
    else:
        print("⚠️ No rMSSD collected.")
        initial_rMSSD = 0
    rMSSD_values = []
    return '', 204

@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    global rMSSD_values, initial_rMSSD, start_collecting, printing_done
    printing_done = False  # 每次新任务重置
    data = request.get_json()
    answers = data.get('answers', {})
    print(f"📥 Received answers: {answers}")

    final_rMSSD = sum(rMSSD_values) / len(rMSSD_values) if rMSSD_values else 0
    delta = final_rMSSD - initial_rMSSD
    print(f"📈 ΔrMSSD = {final_rMSSD:.2f} - {initial_rMSSD:.2f} = {delta:.2f}")
    start_collecting = False
    rMSSD_values = []

    prompt = build_prompt(answers, delta)
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

        # 发送当前时间 + 诗句文本到 Arduino
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

import logging
import sqlite3
import random
import asyncio
import os
import math
import json
import urllib.request
from dotenv import load_dotenv
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- IMPOSTAZIONI ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CANALE_ID = os.getenv("CANALE_ID")
TUO_ID_ADMIN = int(os.getenv("ADMIN_ID"))  # <-- Adesso lo pesca dal file segreto!

MESSAGGI_PER_DROP = 40
MESSAGGI_SCADENZA = 20
TEMPO_SCADENZA_SEC = 120
FILE_JSON = "waifus.json"
PERSONAGGI_PER_PAGINA = 20

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- INIZIALIZZAZIONE DATABASE ---
def setup_db():
    conn = sqlite3.connect('harem.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS harem (user_id INTEGER, waifu_nome TEXT, waifu_serie TEXT)''')
    conn.commit()
    conn.close()
    
    if not os.path.exists(FILE_JSON):
        with open(FILE_JSON, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=4)

def get_random_waifu():
    if not os.path.exists(FILE_JSON): return None, None, None
    with open(FILE_JSON, 'r', encoding='utf-8') as f: waifus = json.load(f)
    if not waifus: return None, None, None
        
    scelta = random.choice(waifus)
    nome = scelta.get('name', 'Sconosciuta')
    serie = scelta.get('series', 'Sconosciuta')
    
    immagini = scelta.get('images', [])
    if not immagini: return None, None, None
    immagine_scelta = random.choice(immagini)
    return nome, serie, immagine_scelta

# --- LOGICA DI SPAWN ED ESCAPE ---
async def waifu_escapes(chat_id, context, message_id):
    if 'active_waifu' in context.chat_data:
        del context.chat_data['active_waifu']
        try:
            await context.bot.send_message(
                chat_id=chat_id, 
                text="💨 *La waifu è scappata via!* Nessuno è stato abbastanza veloce.",
                parse_mode='Markdown'
            )
        except Exception: pass

async def escape_timer(chat_id, context, message_id):
    await asyncio.sleep(TEMPO_SCADENZA_SEC)
    if context.chat_data.get('active_waifu', {}).get('message_id') == message_id:
        await waifu_escapes(chat_id, context, message_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message: return
    chat_id = update.effective_chat.id

    # SPIA 1: Il bot legge i messaggi?
    print(f"[DEBUG] Messaggio letto nel gruppo: {chat_id}")

    if 'msg_count' not in context.chat_data: context.chat_data['msg_count'] = 0

    if 'active_waifu' in context.chat_data:
        context.chat_data['active_waifu']['missed_msgs'] += 1
        if context.chat_data['active_waifu']['missed_msgs'] >= MESSAGGI_SCADENZA:
            msg_id = context.chat_data['active_waifu']['message_id']
            context.chat_data['active_waifu']['timer_task'].cancel()
            await waifu_escapes(chat_id, context, msg_id)
        return

    context.chat_data['msg_count'] += 1
    
    # SPIA 2: Contatore
    print(f"[DEBUG] Contatore per lo spawn: {context.chat_data['msg_count']}/{MESSAGGI_PER_DROP}")

    if context.chat_data['msg_count'] >= MESSAGGI_PER_DROP:
        context.chat_data['msg_count'] = 0 
        
        nome, serie, percorso = get_random_waifu()
        print(f"[DEBUG] Provo a far spawnare: {nome}")
        
        if not nome or not percorso: 
            print("[ERRORE] Il file waifus.json è vuoto o mancano immagini!")
            return

        testo = "🌸 *È apparsa una Waifu!*\n\nCatturala usando il comando */cattura!*"

        try:
            print("[DEBUG] Invio foto in corso...")
            if percorso.startswith("http://") or percorso.startswith("https://"):
                msg = await context.bot.send_photo(chat_id=chat_id, photo=percorso, caption=testo, parse_mode='Markdown')
            elif os.path.exists(percorso):
                with open(percorso, 'rb') as foto:
                    msg = await context.bot.send_photo(chat_id=chat_id, photo=foto, caption=testo, parse_mode='Markdown')
            else:
                # Invio tramite File ID (Cassaforte di Telegram)
                msg = await context.bot.send_photo(chat_id=chat_id, photo=percorso, caption=testo, parse_mode='Markdown')
            print("[DEBUG] FOTO INVIATA CON SUCCESSO! 🎉")
        except Exception as e:
            print(f"[ERRORE CRITICO INVIO FOTO]: {e}")
            return

        timer = asyncio.create_task(escape_timer(chat_id, context, msg.message_id))
        context.chat_data['active_waifu'] = {
            'waifu_nome': nome,
            'waifu_serie': serie,
            'message_id': msg.message_id,
            'missed_msgs': 0,
            'timer_task': timer
        }

# --- COMANDO CATTURA ---
async def comando_cattura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    nome_digitato = " ".join(context.args).strip().lower()
    active = context.chat_data.get('active_waifu')
    
    if not active:
        await update.message.reply_text("❌ Non ci sono waifu da catturare in questo momento!")
        return

    waifu_nome_lower = active['waifu_nome'].lower()
    parole_waifu = waifu_nome_lower.split() 

    if nome_digitato != waifu_nome_lower and nome_digitato not in parole_waifu:
        await update.message.reply_text("❌ Sbagliato! Riprova.")
        return

    waifu_nome = active['waifu_nome']
    waifu_serie = active['waifu_serie']
    chat_id = update.effective_chat.id
    
    active['timer_task'].cancel()
    del context.chat_data['active_waifu']

    conn = sqlite3.connect('harem.db')
    c = conn.cursor()
    c.execute("INSERT INTO harem (user_id, waifu_nome, waifu_serie) VALUES (?, ?, ?)", (user.id, waifu_nome, waifu_serie))
    conn.commit()
    conn.close()

    testo_vittoria = f"🎉 **{user.first_name}** *ha catturato* **{waifu_nome}**"
    if waifu_serie != 'Sconosciuta': testo_vittoria += f" da *{waifu_serie}*!"
    else: testo_vittoria += "!"

    await context.bot.send_message(chat_id=chat_id, text=testo_vittoria, parse_mode='Markdown')

# --- IMPAGINAZIONE HAREM/WAIFU ---
def genera_testo_raggruppato(titolo_intestazione, risultati, pagina, totale_pagine):
    harem_raggruppato = defaultdict(list)
    for nome, serie in risultati: harem_raggruppato[serie].append(nome)
        
    serie_ordinate = sorted(harem_raggruppato.keys())
    testo = f"{titolo_intestazione} (page {pagina}/{totale_pagine}):\n\n"
    contatore_globale = ((pagina - 1) * PERSONAGGI_PER_PAGINA) + 1
    for serie in serie_ordinate:
        testo += f"{serie}\n"
        for waifu in sorted(harem_raggruppato[serie]):
            testo += f"{contatore_globale}. {waifu}\n"
            contatore_globale += 1
        testo += "\n"
    return testo

async def comando_listaharem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('harem.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT waifu_nome, waifu_serie FROM harem WHERE user_id = ?", (user.id,))
    risultati = c.fetchall()
    conn.close()

    if not risultati:
        await update.message.reply_text("Il tuo harem è vuoto! 😭")
        return
        
    totale_pagine = math.ceil(len(risultati) / PERSONAGGI_PER_PAGINA)
    risultati = sorted(risultati, key=lambda x: (x[1], x[0]))
    testo = genera_testo_raggruppato(f"L'harem di {user.first_name}", risultati[0:PERSONAGGI_PER_PAGINA], 1, totale_pagine)

    keyboard = [[InlineKeyboardButton("Successiva ➡️", callback_data=f"listaharempage_{user.id}_2")]] if totale_pagine > 1 else []
    await update.message.reply_text(testo, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

async def listaharem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    owner_id = int(query.data.split("_")[1])
    pagina = int(query.data.split("_")[2])
    
    if query.from_user.id != owner_id: return
        
    conn = sqlite3.connect('harem.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT waifu_nome, waifu_serie FROM harem WHERE user_id = ?", (owner_id,))
    risultati = c.fetchall()
    conn.close()
    
    totale_pagine = math.ceil(len(risultati) / PERSONAGGI_PER_PAGINA)
    risultati = sorted(risultati, key=lambda x: (x[1], x[0]))
    inizio = (pagina - 1) * PERSONAGGI_PER_PAGINA
    testo = genera_testo_raggruppato(f"L'harem di {query.from_user.first_name}", risultati[inizio:inizio+PERSONAGGI_PER_PAGINA], pagina, totale_pagine)
    
    bottoni = []
    if pagina > 1: bottoni.append(InlineKeyboardButton("⬅️ Prec.", callback_data=f"listaharempage_{owner_id}_{pagina - 1}"))
    if pagina < totale_pagine: bottoni.append(InlineKeyboardButton("Succ. ➡️", callback_data=f"listaharempage_{owner_id}_{pagina + 1}"))
    await query.edit_message_text(text=testo, reply_markup=InlineKeyboardMarkup([bottoni]) if bottoni else None)

async def comando_listawaifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(FILE_JSON): return
    with open(FILE_JSON, 'r', encoding='utf-8') as f: dati = json.load(f)
    if not dati: return

    tutte_waifu = sorted([(w.get('name', 'Sconosciuta'), w.get('series', 'Sconosciuta')) for w in dati], key=lambda x: (x[1], x[0]))
    totale_pagine = math.ceil(len(tutte_waifu) / PERSONAGGI_PER_PAGINA)
    testo = genera_testo_raggruppato("📚 **Waifu Disponibili**", tutte_waifu[0:PERSONAGGI_PER_PAGINA], 1, totale_pagine)
        
    keyboard = [[InlineKeyboardButton("Successiva ➡️", callback_data="listapage_2")]] if totale_pagine > 1 else []
    await update.message.reply_text(testo, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

async def listawaifu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pagina = int(query.data.split("_")[1])
    
    with open(FILE_JSON, 'r', encoding='utf-8') as f: dati = json.load(f)
    tutte_waifu = sorted([(w.get('name', 'Sconosciuta'), w.get('series', 'Sconosciuta')) for w in dati], key=lambda x: (x[1], x[0]))
    totale_pagine = math.ceil(len(tutte_waifu) / PERSONAGGI_PER_PAGINA)
    inizio = (pagina - 1) * PERSONAGGI_PER_PAGINA
    
    testo = genera_testo_raggruppato("📚 **Waifu Disponibili**", tutte_waifu[inizio:inizio+PERSONAGGI_PER_PAGINA], pagina, totale_pagine)
    bottoni = []
    if pagina > 1: bottoni.append(InlineKeyboardButton("⬅️ Prec.", callback_data=f"listapage_{pagina - 1}"))
    if pagina < totale_pagine: bottoni.append(InlineKeyboardButton("Succ. ➡️", callback_data=f"listapage_{pagina + 1}"))
    await query.edit_message_text(text=testo, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([bottoni]) if bottoni else None)

# --- COMANDI AMMINISTRATORE ---
async def comando_delwaifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TUO_ID_ADMIN: return
    testo = " ".join(context.args).strip()
    if "|" not in testo: return
        
    nome_waifu, serie_waifu = [t.strip() for t in testo.split("|", 1)]
    with open(FILE_JSON, 'r', encoding='utf-8') as f: dati = json.load(f)
        
    dati_nuovi = [w for w in dati if not (w['name'].lower() == nome_waifu.lower() and w.get('series', '').lower() == serie_waifu.lower())]
    if len(dati) == len(dati_nuovi): return
        
    with open(FILE_JSON, 'w', encoding='utf-8') as f: json.dump(dati_nuovi, f, indent=4)
        
    conn = sqlite3.connect('harem.db')
    c = conn.cursor()
    c.execute("DELETE FROM harem WHERE waifu_nome COLLATE NOCASE = ? AND waifu_serie COLLATE NOCASE = ?", (nome_waifu, serie_waifu))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"🗑️ Waifu **{nome_waifu}** da *{serie_waifu}* eliminata!", parse_mode='Markdown')

async def comando_importawaifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TUO_ID_ADMIN: return
    if not context.args: return await update.message.reply_text("❌ Usa: `/importawaifu Nome`", parse_mode='Markdown')

    nome_ricerca = " ".join(context.args).strip()
    msg_attesa = await update.message.reply_text(f"🔍 Cerco **{nome_ricerca}**...", parse_mode='Markdown')

    query = '''
    query ($search: String) {
      Character(search: $search) {
        id name { full } image { large }
        media(page: 1, perPage: 1, sort: POPULARITY_DESC) { nodes { title { romaji english } } }
      }
    }
    '''
    try:
        req = urllib.request.Request(
            'https://graphql.anilist.co', 
            data=json.dumps({'query': query, 'variables': {'search': nome_ricerca}}).encode('utf-8'), 
            headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        )
        
        with urllib.request.urlopen(req) as response:
            char = json.loads(response.read().decode('utf-8')).get('data', {}).get('Character')
            if not char: return await msg_attesa.edit_text("❌ Personaggio non trovato.")
                
            nome_waifu = char['name']['full']
            immagine_url = char['image']['large']
            serie_waifu = char['media']['nodes'][0]['title'].get('english') or char['media']['nodes'][0]['title'].get('romaji') if char['media']['nodes'] else "Sconosciuta"

            try:
                # Invio al canale segreto
                msg_backup = await context.bot.send_photo(chat_id=int(CANALE_ID), photo=immagine_url, caption=f"📝 ANILIST\n🌸 {nome_waifu}\n📚 {serie_waifu}")
            except Exception:
                req_img = urllib.request.Request(immagine_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_img) as response_img:
                    msg_backup = await context.bot.send_photo(chat_id=int(CANALE_ID), photo=response_img.read(), caption=f"📝 ANILIST\n🌸 {nome_waifu}\n📚 {serie_waifu}")
            
            file_id_salvato = msg_backup.photo[-1].file_id
                
            with open(FILE_JSON, 'r', encoding='utf-8') as f: dati = json.load(f)
            waifu_trovata = False
            
            for w in dati:
                if w['name'].lower() == nome_waifu.lower() and w.get('series', '').lower() == serie_waifu.lower():
                    if file_id_salvato not in w['images']: w['images'].append(file_id_salvato)
                    waifu_trovata = True
                    break
                    
            if not waifu_trovata: dati.append({"id": str(char['id']), "name": nome_waifu, "series": serie_waifu, "images": [file_id_salvato]})
            with open(FILE_JSON, 'w', encoding='utf-8') as f: json.dump(dati, f, indent=4)

            await msg_attesa.delete()
            if waifu_trovata: await update.message.reply_text(f"✅ Aggiunta nuova foto ufficiale a **{nome_waifu}**!", parse_mode='Markdown')
            else: await update.message.reply_text(f"✅ Waifu importata!\n🌸 **{nome_waifu}**\n📚 *{serie_waifu}*", parse_mode='Markdown')

    except Exception as e:
        if "404" in str(e):
            await msg_attesa.edit_text("❌ Personaggio non trovato su AniList!\n\n💡 *Consiglio:* Usa il nome inglese corretto, o prova a scrivere un nome più corto (es. solo Nome e Cognome, senza i secondi nomi).", parse_mode='Markdown')
        else:
            await msg_attesa.edit_text("❌ C'è stato un problema di connessione con i server di AniList.")
        print(f"[DEBUG API] Errore AniList: {e}")

async def aggiungi_waifu_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TUO_ID_ADMIN: return
    if not update.message.caption.startswith("/addwaifu"): return
    
    testo = update.message.caption.replace("/addwaifu", "").strip()
    if "|" not in testo: return
        
    nome_waifu, serie_waifu = [t.strip() for t in testo.split("|", 1)]
    foto = update.message.photo[-1]
    
    msg_backup = await context.bot.send_photo(chat_id=int(CANALE_ID), photo=foto.file_id, caption=f"📝 MANUALE\n🌸 {nome_waifu}\n📚 {serie_waifu}")
    file_id_salvato = msg_backup.photo[-1].file_id
    
    with open(FILE_JSON, 'r', encoding='utf-8') as f: dati = json.load(f)
    waifu_trovata = False
    
    for w in dati:
        if w['name'].lower() == nome_waifu.lower() and w.get('series', '').lower() == serie_waifu.lower():
            if file_id_salvato not in w['images']: w['images'].append(file_id_salvato)
            waifu_trovata = True
            break
            
    if not waifu_trovata: dati.append({"id": foto.file_unique_id, "name": nome_waifu, "series": serie_waifu, "images": [file_id_salvato]})
    with open(FILE_JSON, 'w', encoding='utf-8') as f: json.dump(dati, f, indent=4)
        
    if waifu_trovata: await update.message.reply_text(f"✅ Nuova foto per **{nome_waifu}** salvata in cassaforte!", parse_mode='Markdown')
    else: await update.message.reply_text(f"✅ Nuova waifu in cassaforte!\n🌸 **{nome_waifu}**\n📚 *{serie_waifu}*", parse_mode='Markdown')

# --- AVVIO BOT ---
def main():
    if not TOKEN or not CANALE_ID:
        print("ERRORE CRITICO: Token o ID Canale mancanti nel file .env!")
        return

    setup_db()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("listaharem", comando_listaharem))
    app.add_handler(CallbackQueryHandler(listaharem_callback, pattern="^listaharempage_"))
    app.add_handler(CommandHandler("cattura", comando_cattura))
    app.add_handler(CommandHandler("listawaifu", comando_listawaifu))  
    app.add_handler(CallbackQueryHandler(listawaifu_callback, pattern="^listapage_")) 
    app.add_handler(CommandHandler("delwaifu", comando_delwaifu))
    app.add_handler(CommandHandler("importawaifu", comando_importawaifu))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r'^/addwaifu'), aggiungi_waifu_foto))
    
    # Questo intercetta tutti i messaggi normali e li conta
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot avviato! Modalità spie [DEBUG] attiva. Scrivi nel gruppo per testare.")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
import os
import subprocess
import json
import secrets
import threading
import time
import requests
from flask import Flask, render_template_string, request, jsonify, send_from_directory

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)

# --- CONFIGURAÇÃO DE DIRETÓRIOS (USANDO /TMP PARA O RENDER) ---
# No Render, criar pastas no diretório do app pode dar erro. /tmp é livre.
PASTA_DOWNLOAD = "/tmp" 

# --- CONFIGURAÇÃO YT-DLP ---
YTDLP_ARGS = [
    '--no-check-certificates',
    '--geo-bypass',
    '--extractor-args', 'youtube:player_client=android,web',
    '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# --- SISTEMA DE LAYOUT ---
def render_3d_page(content_html, **kwargs):
    base_html = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MusicDash 3D | Player</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Outfit', sans-serif; background: #f0f2f9; color: #1b2559; overflow-x: hidden; }}
            .card-3d {{ background: white; border-radius: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); transition: 0.3s; border: 1px solid rgba(255,255,255,0.8); }}
            .card-3d:hover {{ transform: translateY(-5px); box-shadow: 0 20px 40px rgba(67, 24, 255, 0.1); }}
            .btn-grad {{ background: linear-gradient(135deg, #4318FF 0%, #868CFF 100%); color: white; transition: 0.3s; }}
            .btn-grad:hover {{ transform: scale(1.02); opacity: 0.9; }}
            .loader-spin {{ border-top-color: #4318FF; animation: spin 1s linear infinite; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
            audio {{ width: 100%; border-radius: 50px; }}
        </style>
    </head>
    <body class="min-h-screen">
        {content_html}
        <div id="loader" class="hidden fixed inset-0 bg-white/90 backdrop-blur-md z-[100] flex flex-col items-center justify-center">
            <div class="w-16 h-16 border-4 border-slate-100 loader-spin rounded-full"></div>
            <p class="mt-4 font-bold text-indigo-600 animate-pulse">PROCESSANDO ÁUDIO...</p>
        </div>
        <script>
            function showLoader() {{ document.getElementById('loader').classList.remove('hidden'); }}
        </script>
    </body>
    </html>
    """
    return render_template_string(base_html, **kwargs)

# --- TEMPLATES DE CONTEÚDO ---

HOME_CONTENT = """
    <div class="max-w-4xl mx-auto p-6">
        <div class="text-center my-12">
            <div class="inline-block p-4 bg-white rounded-3xl shadow-sm mb-4">
                <i class="fas fa-compact-disc fa-spin text-4xl text-indigo-600"></i>
            </div>
            <h1 class="text-5xl font-black mb-4 text-slate-800 tracking-tighter">MUSIC<span class="text-indigo-600">3D</span></h1>
            <p class="text-slate-500">Busque e transforme links em MP3 Instantâneo</p>
        </div>

        <div class="relative mb-10 group">
            <input type="text" id="searchInput" 
                class="w-full p-6 rounded-3xl shadow-xl border-none outline-none text-lg transition-all focus:ring-4 focus:ring-indigo-100" 
                placeholder="Nome da música ou artista..."
                onkeypress="if(event.key==='Enter') search()">
            <button onclick="search()" class="btn-grad absolute right-3 top-3 bottom-3 px-8 rounded-2xl font-bold shadow-lg">Buscar</button>
        </div>

        <div id="results" class="grid grid-cols-1 md:grid-cols-2 gap-6"></div>
    </div>

    <script>
        async function search() {
            const q = document.getElementById('searchInput').value;
            if(!q) return;
            showLoader();
            try {
                const res = await fetch('/api/search', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: q})
                });
                const data = await res.json();
                const div = document.getElementById('results');
                div.innerHTML = '';
                data.forEach(m => {
                    div.innerHTML += `
                        <div class="card-3d p-4 flex items-center gap-4">
                            <img src="${m.thumbnail}" class="w-20 h-20 rounded-xl object-cover shadow-md">
                            <div class="flex-1 overflow-hidden">
                                <h3 class="font-bold truncate text-sm text-slate-800">${m.title}</h3>
                                <p class="text-xs text-indigo-500 font-bold mb-2">${m.duration}</p>
                                <a href="/player/${m.id}?title=${encodeURIComponent(m.title)}" 
                                   onclick="showLoader()" 
                                   class="inline-block bg-indigo-50 text-indigo-600 px-4 py-2 rounded-xl font-bold text-[10px] uppercase transition hover:bg-indigo-600 hover:text-white">
                                   Ouvir Música
                                </a>
                            </div>
                        </div>
                    `;
                });
            } catch (e) { alert("Erro ao buscar"); }
            finally { document.getElementById('loader').classList.add('hidden'); }
        }
    </script>
"""

PLAYER_CONTENT = """
    <div class="max-w-2xl mx-auto p-6 mt-10">
        <a href="/" class="text-slate-400 hover:text-indigo-600 transition flex items-center gap-2 mb-8 font-bold">
            <i class="fas fa-chevron-left"></i> VOLTAR PARA BUSCA
        </a>

        <div class="card-3d p-8 text-center relative overflow-hidden">
            <div class="absolute top-0 left-0 w-full h-2 btn-grad"></div>
            <img src="https://img.youtube.com/vi/{{ vid }}/maxresdefault.jpg" class="w-full rounded-3xl shadow-2xl mb-8 border-4 border-white">
            
            <h2 class="text-2xl font-black mb-2 text-slate-800 leading-tight">{{ title }}</h2>
            <div class="flex justify-center gap-2 mb-8">
                <span class="bg-indigo-100 text-indigo-600 text-[10px] px-3 py-1 rounded-full font-bold uppercase">MP3 320kbps</span>
            </div>

            <audio id="player" controls autoplay class="mb-8">
                <source src="/play/{{ filename }}" type="audio/mpeg">
            </audio>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <a href="/force_download/{{ filename }}?title={{ title }}" 
                   class="btn-grad py-4 rounded-2xl font-bold flex items-center justify-center gap-2 shadow-xl">
                    <i class="fas fa-download"></i> BAIXAR AGORA
                </a>
                <button onclick="share()" class="bg-slate-800 text-white py-4 rounded-2xl font-bold flex items-center justify-center gap-2 hover:bg-black transition">
                    <i class="fas fa-share-alt"></i> COMPARTILHAR
                </button>
            </div>
            <p class="mt-6 text-[10px] text-slate-300 font-bold uppercase tracking-widest">Processado pelo Servidor MusicDash</p>
        </div>
    </div>

    <script>
        function share() {
            const url = window.location.href;
            navigator.clipboard.writeText(url);
            alert("Link de compartilhamento copiado!");
        }
    </script>
"""

# --- ROTAS ---

@app.route('/')
def home():
    return render_3d_page(HOME_CONTENT)

@app.route('/api/search', methods=['POST'])
def api_search():
    query = request.json.get('query')
    # Limitado a 5 resultados para ser rápido no Render
    cmd = ['yt-dlp'] + YTDLP_ARGS + ['--quiet', '--no-playlist', '--flat-playlist', '--dump-json', f'ytsearch5:{query}']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        videos = [json.loads(line) for line in result.stdout.splitlines()]
        results = []
        for v in videos:
            d = v.get('duration', 0)
            results.append({
                'id': v['id'],
                'title': v['title'],
                'thumbnail': f"https://img.youtube.com/vi/{v['id']}/mqdefault.jpg",
                'duration': f"{int(d//60)}:{int(d%60):02d}"
            })
        return jsonify(results)
    except:
        return jsonify([])

@app.route('/player/<vid>')
def player(vid):
    title = request.args.get('title', 'Musica')
    filename = f"{vid}.mp3"
    filepath = os.path.join(PASTA_DOWNLOAD, filename)

    if not os.path.exists(filepath):
        # Baixa diretamente na /tmp
        cmd = ['yt-dlp'] + YTDLP_ARGS + [
            '--extract-audio', '--audio-format', 'mp3', 
            '--audio-quality', '0', '--output', filepath,
            f'https://www.youtube.com/watch?v={vid}'
        ]
        subprocess.run(cmd)

    return render_3d_page(PLAYER_CONTENT, vid=vid, title=title, filename=filename)

@app.route('/play/<path:name>')
def play(name):
    return send_from_directory(PASTA_DOWNLOAD, name)

@app.route('/force_download/<path:name>')
def force_download(name):
    title = request.args.get('title', 'Musica')
    clean_name = "".join([c for c in title if c.isalnum() or c in ' -_']).strip() + ".mp3"
    return send_from_directory(PASTA_DOWNLOAD, name, as_attachment=True, download_name=clean_name)

@app.route('/ping')
def ping():
    return "Acordado!", 200

# --- ANTI-SLEEP ---
def anti_sleep():
    url_render = os.environ.get("RENDER_EXTERNAL_URL")
    if not url_render: return
    
    while True:
        try:
            requests.get(f"{url_render}/ping", timeout=10)
        except:
            pass
        time.sleep(600) # Ping a cada 10 min

# --- INICIALIZAÇÃO ---
if __name__ == '__main__':
    if os.environ.get("RENDER"):
        threading.Thread(target=anti_sleep, daemon=True).start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# Pagination state for each user
user_search_state = {}
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# Start the Flask server in a separate thread
Thread(target=run_flask).start()
import sys
import subprocess
import os

from dotenv import load_dotenv

def check_and_install_requirements():
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not os.path.exists(req_file):
        print("requirements.txt not found!")
        sys.exit(1)
    print("🔧 Checking and installing required packages...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        print("✅ All packages installed successfully!")
    except Exception as e:
        print(f"❌ Failed to install requirements: {e}")
        sys.exit(1)

check_and_install_requirements()
load_dotenv()
print("🚀 Starting the music downloader bot...")

import os
import re
import logging
import tempfile
import asyncio
import aiohttp
import concurrent.futures
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK
from mutagen.mp3 import MP3
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from urllib.parse import urlparse, parse_qs
import time

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET')

# Set up Spotify client
def setup_spotify_client():
    """Set up and return Spotify client"""
    # Create a dedicated cache folder for Spotipy token
    # Remove cache_path, use default Spotipy client credentials (no persistent cache)
    auth_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
    # Silence Spotipy cache warnings
    import logging
    logging.getLogger('spotipy.cache_handler').setLevel(logging.ERROR)
    return spotipy.Spotify(auth_manager=auth_manager)

# Initialize Spotify client
sp = setup_spotify_client()

# Thread pool for parallel execution
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# Function to sanitize filenames
def sanitize_filename(name):
    """Remove invalid characters from filenames"""
    return re.sub(r'[<>:"/\\|?*]', '', name)

# Spotify functions
def get_track_info(track_url):
    """Get track information from Spotify"""
    try:
        track_id = track_url.split('/')[-1].split('?')[0]
        # Remove timeout from Spotify client
        track = sp.track(track_id)
        return {
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'album': track['album']['name'],
            'album_art': track['album']['images'][0]['url'] if track['album']['images'] else None,
            'release_date': track['album']['release_date'],
            'track_number': track['track_number'],
            'duration_ms': track['duration_ms'],
            'url': track_url
        }
    except Exception as e:
        logger.error(f"Error getting track info: {e}")
        return None

# YouTube Music functions - OPTIMIZED
def get_youtube_video_info_fast(url):
    """Fast video information extraction"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ignoreerrors': True,
        'extract_flat': 'in_playlist',
        'force_json': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error getting YouTube video info: {e}")
        return {"error": str(e)}

# Fast search function
def search_youtube_fast(query):
    """Fast YouTube search"""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_json': True,
        'ignoreerrors': True,
    'default_search': 'ytsearch50',  # Search top 50 results
        'noplaylist': True,
    }

    try:
        logger.warning(f"Starting YouTube search for query: '{query}'")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch50:{query}", download=False)
            logger.warning(f"yt-dlp returned info: {info}")
            if info and 'entries' in info and info['entries']:
                query_lower = query.lower()
                # Log all candidate results for debugging
                logger.warning(f"YouTube search candidates for '{query}':")
                for idx, entry in enumerate(info['entries']):
                    if entry and 'title' in entry:
                        logger.warning(f"[{idx+1}] Title: {entry['title']} | URL: {entry.get('url', 'N/A')}")
                # Try to find the best match by comparing title and artist
                for entry in info['entries']:
                    if entry and 'title' in entry:
                        title = entry['title'].lower()
                        # Check for exact match
                        if query_lower in title:
                            return entry['url']
                        # Check for partial match (artist and song)
                        if all(part.strip() in title for part in query_lower.split(' - ')):
                            return entry['url']
                # Fallback: return the first result
                return info['entries'][0]['url']
            else:
                logger.warning(f"No entries found in yt-dlp info for query: '{query}'. Raw info: {info}")
    except Exception as e:
        logger.error(f"Fast search failed: {e}")

    return None

# FAST Download functions
def download_audio_fast(youtube_url, output_path, track_info=None):
    import time
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',  # Prefer m4a (fast, good quality), fallback to best
        'outtmpl': output_path.replace('.mp3', ''),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '160',  # Slightly lower for speed, still good quality
        }],
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'retries': 1,  # Fewer retries for speed
        'fragment_retries': 1,
        'skip_unavailable_fragments': True,
        'noprogress': True,
        'nooverwrites': True,
        'nopart': True,
        'http_chunk_size': 5242880,  # 5MB chunks for faster download
        'concurrent_fragment_downloads': 2,  # Fewer parallel downloads for stability
        'extract_flat': False,
    }
    try:
        logger.info(f"[Timing] yt-dlp download started for {youtube_url}")
        start_time = time.time()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        logger.info(f"[Timing] yt-dlp download finished in {time.time() - start_time:.2f} seconds.")
        base_path = output_path.replace('.mp3', '')
        for ext in ['.mp3', '.m4a', '.webm']:
            if os.path.exists(base_path + ext):
                if ext != '.mp3':
                    os.rename(base_path + ext, output_path)
                if track_info:
                    add_metadata_fast(output_path, track_info)
                return True
        return False
    except Exception as e:
        logger.error(f"Fast download failed: {e}")
        return False

def add_metadata_fast(file_path, track_info):
    """Fast metadata addition"""
    try:
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except:
            pass
        audio['TIT2'] = TIT2(encoding=3, text=track_info.get('name', 'Unknown Title'))
        audio['TPE1'] = TPE1(encoding=3, text=track_info.get('artist', 'Unknown Artist'))
        # Add album art only if it's quick
        if track_info.get('album_art'):
            try:
                # Remove timeout from requests.get
                response = requests.get(track_info['album_art'])
                if response.status_code == 200:
                    audio.tags.add(
                        APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc='Cover',
                            data=response.content
                        )
                    )
            except:
                pass
        audio.save()
        return True
    except Exception as e:
        logger.error(f"Error adding metadata: {e}")
        return False

# Async functions for parallel processing
async def run_in_executor(func, *args):
    """Run function in thread pool executor"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

# Main download functions - OPTIMIZED
async def download_spotify_track_fast(track_url, update, processing_msg):
    try:
        step_start = time.time()
        logger.info("[Timing] Starting Spotify API call...")
        # Notify user during Spotify API call
        await processing_msg.edit_text(
            "🎧 Getting track info from Spotify... Please wait, this may take a while if the network is slow.",
            parse_mode='Markdown'
        )
        track_info = await run_in_executor(get_track_info, track_url)
        logger.info(f"[Timing] Spotify API call took {time.time() - step_start:.2f} seconds.")
        if not track_info:
            await processing_msg.edit_text(
                "❌ *Error* \n\nCould not get track information.",
                parse_mode='Markdown'
            )
            return False
        query = f"{track_info['artist']} - {track_info['name']}"
        step_start = time.time()
        logger.info("[Timing] Starting YouTube search...")
        await processing_msg.edit_text(
            f"🔍 Searching YouTube for `{query}`... Please wait, this may take a while.",
            parse_mode='Markdown'
        )
        youtube_url = await run_in_executor(search_youtube_fast, query)
        query = f"{track_info['artist']} - {track_info['name']}"
        step_start = time.time()
        logger.info("[Timing] Starting YouTube search...")
        await processing_msg.edit_text(
            f"🔍 Searching YouTube for `{query}`... Please wait, this may take a while.",
            parse_mode='Markdown'
        )
        youtube_url = await run_in_executor(search_youtube_fast, query)
        logger.info(f"[Timing] YouTube search took {time.time() - step_start:.2f} seconds.")
        # Only proceed if a valid YouTube URL is found
        if not youtube_url or not (youtube_url.startswith('http') and ('youtube.com' in youtube_url or 'youtu.be' in youtube_url)):
            await processing_msg.edit_text(
                f"❌ *Sorry, I couldn't find a YouTube version for* \n`{query}`.\nPlease try another track or check the spelling.",
                parse_mode='Markdown'
            )
            return False
        output_path = tmp_file.name
        f"⬇️ Downloading `{track_info['name']}` by {track_info['artist']}... Please wait, this may take a while.",
        parse_mode='Markdown'
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
            output_path = tmp_file.name
        success = await run_in_executor(download_audio_fast, youtube_url, output_path, track_info)
        if success:
            await processing_msg.edit_text(
                f"✅ *Complete!* \n\nSending `{track_info['name']}`...",
                parse_mode='Markdown'
            )
            try:
                with open(output_path, 'rb') as audio_file:
                    await update.message.reply_audio(
                        audio=audio_file,
                        title=track_info['name'][:64],
                        performer=track_info['artist'][:64],
                        caption=f"🎵 *{track_info['name']}* by {track_info['artist']}",
                        parse_mode='Markdown',
                        filename=f"{sanitize_filename(track_info['artist'])} - {sanitize_filename(track_info['name'])}.mp3"
                    )
            except Exception as send_err:
                # If file was sent despite error, do not send error message
                logger.error(f"Error sending audio: {send_err}")
                # Check if file was sent (Telegram API may throw timeout but still deliver)
                # If not sent, send error message
                # (No reliable way to check, so just log and skip user error message)
                pass
            try:
                os.unlink(output_path)
            except Exception as cleanup_err:
                logger.warning(f"Cleanup error: {cleanup_err}")
            return True
        else:
            await processing_msg.edit_text(
                f"❌ *Download Failed* \n\nCould not download `{track_info['name']}`",
                parse_mode='Markdown'
            )
            return False
    except Exception as e:
        logger.error(f"Error processing track: {e}")
        # Only send error if no file was sent
        # (No reliable way to check, so just log and skip user error message)
        pass
    return False

async def download_youtube_music_fast(url, update, processing_msg):
    """Fast YouTube Music download"""
    try:
        await processing_msg.edit_text(
            "🎵 *Processing* \n\nGetting video info...",
            parse_mode='Markdown'
        )
        
        # Fast video info extraction
        video_info = await run_in_executor(get_youtube_video_info_fast, url)
        if not video_info or "error" in video_info:
            await processing_msg.edit_text(
                "❌ Error getting video info",
                parse_mode='Markdown'
            )
            return False
        
        title = video_info.get('title', 'Unknown Title')[:64]
        uploader = video_info.get('uploader', 'Unknown Artist')[:64]
        
        await processing_msg.edit_text(
            f"⬇️ *Downloading* \n`{title}`",
            parse_mode='Markdown'
        )
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
            output_path = tmp_file.name
        
        # Fast download
        success = await run_in_executor(download_audio_fast, url, output_path)
        
        if success:
            await processing_msg.edit_text(
                f"✅ *Complete!* \n\nSending `{title}`...",
                parse_mode='Markdown'
            )
            
            # Send the audio file
            with open(output_path, 'rb') as audio_file:
                    await update.message.reply_audio(
                        audio=audio_file,
                        title=title,
                        performer=uploader,
                        caption=f"🎵 *{title}* by {uploader}",
                        parse_mode='Markdown',
                        filename=f"{sanitize_filename(uploader)} - {sanitize_filename(title)}.mp3"
                    )
            
            # Clean up
            try:
                os.unlink(output_path)
            except:
                pass
                
            return True
        else:
            await processing_msg.edit_text(
                f"❌ *Download Failed* \n\nCould not download `{title}`",
                parse_mode='Markdown'
            )
            return False
            
    except Exception as e:
        logger.error(f"Error processing YouTube: {e}")
        await processing_msg.edit_text(
            "❌ *Error* \n\nPlease try again later.",
            parse_mode='Markdown'
        )
        return False

async def download_spotify_playlist_fast(playlist_url, update, processing_msg):
    try:
        await processing_msg.edit_text(
            "🎧 Getting playlist info from Spotify... Please wait, this may take a while if the network is slow.",
            parse_mode='Markdown'
        )
        playlist_id = playlist_url.split('/playlist/')[-1].split('?')[0]
        playlist = sp.playlist(playlist_id)
        playlist_name = playlist.get('name', 'Spotify Playlist')
        tracks = playlist['tracks']['items']
        total = len(tracks)
        track_files = []
        await processing_msg.edit_text(
            f"🔍 Searching on YouTube for *{playlist_name}*...",
            parse_mode='Markdown'
        )
        for idx, item in enumerate(tracks, 1):
            track = item['track']
            track_url = f"https://open.spotify.com/track/{track['id']}"
            await processing_msg.edit_text(
                f"🎵 Downloading {track['name']} by {track['artists'][0]['name']} ({idx}/{total})...",
                parse_mode='Markdown'
            )
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                output_path = tmp_file.name
            success = await download_spotify_track_fast_collect(track_url, output_path)
            if success:
                track_files.append((output_path, track['name'], track['artists'][0]['name']))
        await processing_msg.edit_text(
            f"✅ *Playlist Downloaded!* \n\nSending all {len(track_files)} tracks...",
            parse_mode='Markdown'
        )
        # Send all files only after all downloads are complete
        for file_path, name, artist in track_files:
            try:
                with open(file_path, 'rb') as audio_file:
                    await update.message.reply_audio(
                        audio=audio_file,
                        title=name[:64],
                        performer=artist[:64],
                        caption=f"🎵 *{name}* by {artist}",
                        parse_mode='Markdown',
                        filename=f"{sanitize_filename(artist)} - {sanitize_filename(name)}.mp3"
                    )
            except Exception as send_err:
                logger.error(f"Error sending audio: {send_err}")
            try:
                os.unlink(file_path)
            except Exception as cleanup_err:
                logger.warning(f"Cleanup error: {cleanup_err}")
        await processing_msg.edit_text(
            f"✅ *All tracks sent!* \n\nSend another link! 🎧",
            parse_mode='Markdown'
        )
        return True
    except Exception as e:
        logger.error(f"Error processing playlist: {e}")
        await processing_msg.edit_text(
            f"❌ *Error* \n\nCould not process playlist.",
            parse_mode='Markdown'
        )
        return False

async def download_spotify_track_fast_collect(track_url, output_path):
    try:
        track_info = await run_in_executor(get_track_info, track_url)
        if not track_info:
            return False
        query = f"{track_info['artist']} - {track_info['name']}"
        youtube_url = await run_in_executor(search_youtube_fast, query)
        if not youtube_url:
            return False
        success = await run_in_executor(download_audio_fast, youtube_url, output_path, track_info)
        return success
    except Exception as e:
        logger.error(f"Error processing track (collect): {e}")
        return False

# Telegram Bot Handlers - OPTIMIZED
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fast welcome message"""
    welcome_text = """
🎵 *Fast Music Downloader Bot!* 🎵

I quickly download music from Spotify and YouTube Music!

✨ *Supported:*
• Spotify tracks
• YouTube Music videos
• Regular YouTube videos
• Music title or artist search


📝 *Just send me a link!  or a name!*

⚡ *Optimized for speed!*
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fast help message"""
    help_text = """
🤖 *Quick Help*

*Commands:*
/start - Welcome message
/help - This help

*Just send any:*
• Spotify track link
• YouTube Music link
• YouTube link

⚡ *Fast downloads!*
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def search_and_select_youtube(update, processing_msg, query):
    try:
        await processing_msg.edit_text(
            f"🔍 Searching YouTube for `{query}`... Please wait.",
            parse_mode='Markdown'
        )
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'force_json': True,
            'ignoreerrors': True,
            'default_search': 'ytsearch50',
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch50:{query}", download=False)
        logger.warning(f"yt-dlp raw info for search: {info}")
        if not info or 'entries' not in info or not info['entries']:
            await processing_msg.edit_text(
                f"❌ No results found for `{query}`.",
                parse_mode='Markdown'
            )
            return None
        results = info['entries']
        user_id = update.effective_user.id
        user_search_state[user_id] = {
            'results': results,
            'page': 0
        }
        return await send_search_page(update, processing_msg, user_id)

    except Exception as e:
        logger.error(f"Error searching YouTube: {e}")
        

# Helper to send a page of search results
async def send_search_page(update, processing_msg, user_id):
    try:
        state = user_search_state[user_id]
        results = state['results']
        page = state['page']
        page_size = 10
        start = page * page_size
        end = start + page_size
        page_results = results[start:end]
        def escape_md(text):
            # Telegram Markdown V2 escaping
            if not text:
                return ''
            return re.sub(r'([_\*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

        msg_lines = [
            f"*{start + i + 1}.*\n  🎵 *Title:* {escape_md(entry.get('title', 'Unknown'))}\n  👤 *Artist:* {escape_md(entry.get('uploader', 'Unknown Artist'))}\n  ⏱️ *Duration:* {int(entry.get('duration', 0))//60}:{int(entry.get('duration', 0))%60:02d} min\n" + ("────────────────────────────" if i < len(page_results)-1 else "")
            for i, entry in enumerate(page_results)
        ]
        msg_lines.append("Send a number to download, 'all' to download all, or use the 'discard' button to cancel.")
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = []
        # Previous page button
        if page > 0:
            keyboard.append([InlineKeyboardButton("← Previous page", callback_data="prev_page")])
        # Next page button (always show unless on last page)
        if end < len(results) or page == 0:
            keyboard.append([InlineKeyboardButton("Next page →", callback_data="next_page")])
        # Discard button
        keyboard.append([InlineKeyboardButton("Discard", callback_data="discard_search")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await processing_msg.edit_text(
            f"*Select a song by number:*\n\n" + "\n".join(msg_lines),
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return results
    except Exception as e:
        logger.error(f"Error searching YouTube: {e}")
        await processing_msg.edit_text(
            f"❌ Error searching YouTube.",
            parse_mode='Markdown'
        )
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    message_text = ''
    if hasattr(update, 'message') and update.message and hasattr(update.message, 'text') and update.message.text:
        message_text = update.message.text.strip()
    user_id = update.effective_user.id
    # Artist link support
    if 'open.spotify.com' in message_text and '/artist/' in message_text:
        # Send processing message first
        processing_msg = await update.message.reply_text(
            "⚡️ Processing...\nThis will be fast! 🚀",
            parse_mode='Markdown'
        )
        artist_id = message_text.split('/artist/')[-1].split('?')[0]
        artist = sp.artist(artist_id)
        artist_name = artist.get('name', 'Spotify Artist')
        # Fetch all albums by artist
        albums = sp.artist_albums(artist_id, album_type='album,single', limit=50)
        album_ids = [album['id'] for album in albums['items']]
        # Collect all tracks from all albums
        tracks = []
        for album_id in album_ids:
            album = sp.album(album_id)
            for track in album['tracks']['items']:
                tracks.append({
                    'url': f"https://open.spotify.com/track/{track['id']}",
                    'title': track['name'],
                    'uploader': artist_name,
                    'duration': int(track['duration_ms']) // 1000
                })
        # Remove duplicates by track id
        seen = set()
        unique_tracks = []
        for t in tracks:
            tid = t['url']
            if tid not in seen:
                seen.add(tid)
                unique_tracks.append(t)
        user_search_state[user_id] = {
            'results': unique_tracks,
            'page': 0,
            'artist_name': artist_name
        }
        # Send found artist message like playlist
        await processing_msg.edit_text(
            f"Found artist *{artist_name}* — preparing to send over to you...",
            parse_mode='Markdown'
        )
        # Send selection instructions and first page
        processing_msg = await update.message.reply_text(
            f"*{artist_name}*\n\nSelect tracks to download by replying with numbers (e.g. 1,2,3) or 'all' to download all.\n\nListing all {len(unique_tracks)} tracks...",
            parse_mode='Markdown'
        )
        await send_search_page(update, processing_msg, user_id)
        return
    message_text = ''
    if hasattr(update, 'message') and update.message and hasattr(update.message, 'text') and update.message.text:
        message_text = update.message.text.strip()
    user_id = update.effective_user.id
    # If user is in search state, handle reply
    if user_id in user_search_state:
        state = user_search_state[user_id]
        results = state['results']
        page = state['page']
        page_size = 10
        start = page * page_size
        end = start + page_size
        text = message_text.lower()
        # Handle multiple selection (e.g. "1,2,3")
        if ',' in text:
            try:
                indices = [int(x.strip()) for x in text.split(',') if x.strip().isdigit() and 1 <= int(x.strip()) <= len(results)]
            except Exception:
                indices = []
        else:
            indices = []
            if text.isdigit() and 1 <= int(text) <= len(results):
                indices = [int(text)]
        if indices:
            total = len(indices)
            file_queue = []
            for idx, number in enumerate(indices, 1):
                entry = results[number-1]
                url = entry.get('url')
                name = entry.get('title', 'Unknown')
                artist = entry.get('uploader', 'Unknown Artist')
                duration = int(entry.get('duration', 0) or 0)
                msg = await update.message.reply_text(
                    f"⬇️ Downloading `{name}` by {artist} ({idx}/{total})...",
                    parse_mode='Markdown'
                )
                yt_query = f"{artist} - {name}"
                youtube_url = await run_in_executor(search_youtube_fast, yt_query)
                if not youtube_url or not (youtube_url.startswith('http') and ('youtube.com' in youtube_url or 'youtu.be' in youtube_url)):
                    await msg.edit_text(
                        f"❌ *Sorry, I couldn't find a YouTube version for* \n`{yt_query}`. Skipping.",
                        parse_mode='Markdown'
                    )
                    continue
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                    output_path = tmp_file.name
                download_success = False
                for attempt in range(3):
                    try:
                        success = await run_in_executor(download_audio_fast, youtube_url, output_path)
                        # Check if file exists and is nonzero size
                        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            download_success = True
                            break
                    except Exception as ext_err:
                        logger.error(f"External error during download: {ext_err}")
                        # Do not notify user for external errors unless all attempts fail
                        pass
                if download_success:
                    await msg.edit_text(
                    f"✅ Done, sending to you...",
                    parse_mode='Markdown'
                    )                
                    file_queue.append((output_path, name, artist))
                else:
                    await msg.edit_text(
                        f"❌ *Download failed for* `{name}` by {artist} after several attempts. Skipping.",
                        parse_mode='Markdown'
                    )
            # Send all files only after all downloads are complete
            sent_count = 0
            failed_files = []
            total_files = len(file_queue)
            for idx, (file_path, name, artist) in enumerate(file_queue, 1):
                try:
                    # Wait for file to finish downloading if needed
                    for _ in range(10):
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                            break
                        await asyncio.sleep(1)
                    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                        logger.error(f"File not ready for sending: {file_path}")
                        failed_files.append(name)
                        continue
                    with open(file_path, 'rb') as audio_file:
                        await update.message.reply_audio(
                            audio=audio_file,
                            title=name[:64],
                            performer=artist[:64],
                            caption=f"🎵 *{name}* by {artist} ({idx}/{total_files})",
                            parse_mode='Markdown',
                            filename=f"{sanitize_filename(artist)} - {sanitize_filename(name)}.mp3"
                        )
                    sent_count += 1
                except Exception as send_err:
                    logger.error(f"Error sending audio: {send_err}")
                    failed_files.append(name)
                    # Only notify user if file is confirmed ready but sending fails
                    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                        await update.message.reply_text(
                            f"❌ *Failed to send* `{name}` by {artist}. Please try again.",
                            parse_mode='Markdown'
                        )
                finally:
                    try:
                        os.unlink(file_path)
                    except:
                        pass
            if sent_count == total_files:
                await update.message.reply_text(
                    f"✅ All {sent_count}/{total_files} files sent! You can send another name or link to start a new search.",
                    parse_mode='Markdown'
                )
            elif sent_count > 0:
                fail_list = ', '.join(failed_files)
                await update.message.reply_text(
                    f"✅ {sent_count}/{total_files} files sent. ❌ {total_files-sent_count}/{total_files} could not be sent ({fail_list}). Please try again.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ No files were sent. Please try the process again.",
                    parse_mode='Markdown'
                )
            del user_search_state[user_id]
            return
        # Discard
        if text == 'discard':
            del user_search_state[user_id]
            await update.message.reply_text("Search discarded. Send a new song or artist name.")
            return
        # Next page
        if text.isdigit():
            number = int(text)
            if number == end + 1 and end < len(results):
                state['page'] += 1
                processing_msg = await update.message.reply_text("Next page...", parse_mode='Markdown')
                await send_search_page(update, processing_msg, user_id)
                return
            # Download single by absolute number
            if 1 <= number <= len(results):
                entry = results[number-1]
                url = entry.get('url')
                name = entry.get('title', 'Unknown')
                artist = entry.get('uploader', 'Unknown Artist')
                duration = int(entry.get('duration', 0) or 0)
                msg = await update.message.reply_text(
                    f"⬇️ Downloading `{name}` by {artist} ({duration//60}:{duration%60:02d} min)...",
                    parse_mode='Markdown'
                )
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                    output_path = tmp_file.name
                success = await run_in_executor(download_audio_fast, url, output_path)
                if success:
                    with open(output_path, 'rb') as audio_file:
                        await update.message.reply_audio(
                            audio=audio_file,
                            title=name[:64],
                            performer=artist[:64],
                            caption=f"🎵 *{name}* by {artist}",
                            parse_mode='Markdown',
                            filename=f"{sanitize_filename(artist)} - {sanitize_filename(name)}.mp3"
                        )
                    try:
                        os.unlink(output_path)
                    except:
                        pass
                await msg.edit_text(
                    f"✅ *Done!* \n\nSend another name or link! 🎧",
                    parse_mode='Markdown'
                )
                del user_search_state[user_id]
                return
            else:
                await update.message.reply_text(
                    "❌ Invalid number. Please reply with a valid song number.",
                    parse_mode='Markdown'
                )
                return
        # Otherwise, treat as search query
        processing_msg = await update.message.reply_text(
            "🔍 Searching for your song or artist...",
            parse_mode='Markdown'
        )
        await search_and_select_youtube(update, processing_msg, message_text)
        return
    # Quick processing message
    processing_msg = await update.message.reply_text(
        "⚡ *Processing...* \n\nThis will be fast! 🚀",
        parse_mode='Markdown'
    )
    try:
        # Fast processing based on link type
        if 'open.spotify.com' in message_text and '/album/' in message_text:
            album_id = message_text.split('/album/')[-1].split('?')[0]
            album = sp.album(album_id)
            album_name = album.get('name', 'Spotify Album')
            tracks = album['tracks']['items']
            next_url = album['tracks']['next']
            while next_url:
                next_tracks = sp._get(next_url)
                tracks.extend(next_tracks['items'])
                next_url = next_tracks['next']
            user_search_state[user_id] = {
                'results': [
                    {
                        'url': f"https://open.spotify.com/track/{track['id']}",
                        'title': track['name'],
                        'uploader': track['artists'][0]['name'],
                        'duration': int(track['duration_ms']) // 1000
                    } for track in tracks
                ],
                'page': 0,
                'album_name': album_name
            }
            await processing_msg.edit_text(
                f"Found album *{album_name}* — preparing to send over to you...",
                parse_mode='Markdown'
            )
            processing_msg = await update.message.reply_text(
                f"*{album_name}*\n\nSelect tracks to download by replying with numbers (e.g. 1,2,3) or 'all' to download all.\n\nListing all {len(tracks)} tracks...",
                parse_mode='Markdown'
            )
            await send_search_page(update, processing_msg, user_id)
            return
        if 'open.spotify.com' in message_text and '/playlist/' in message_text:
            playlist_id = message_text.split('/playlist/')[-1].split('?')[0]
            playlist = sp.playlist(playlist_id)
            playlist_name = playlist.get('name', 'Spotify Playlist')
            tracks = playlist['tracks']['items']
            # Collect all tracks with pagination
            next_url = playlist['tracks']['next']
            while next_url:
                next_tracks = sp._get(next_url)
                tracks.extend(next_tracks['items'])
                next_url = next_tracks['next']
            # Prepare results for user selection
            user_id = update.effective_user.id
            user_search_state[user_id] = {
                'results': [
                    {
                        'url': f"https://open.spotify.com/track/{track['track']['id']}",
                        'title': track['track']['name'],
                        'uploader': track['track']['artists'][0]['name'],
                        'duration': int(track['track']['duration_ms']) // 1000
                    } for track in tracks if track.get('track') and track['track'].get('id')
                ],
                'page': 0,
                'playlist_name': playlist_name
            }
            await processing_msg.edit_text(
                f"Found playlist *{playlist_name}* — preparing to send over to you...",
                parse_mode='Markdown'
            )
            # Format message as requested
            def escape_md(text):
                if not text:
                    return ''
                return re.sub(r'([_\*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))
            msg_lines = [
                f"*{i+1}.*\n  🎵 *Title:* {escape_md(entry['title'])}\n  👤 *Artist:* {escape_md(entry['uploader'])}\n  ⏱️ *Duration:* {entry['duration']//60}:{entry['duration']%60:02d} min" + ("\n────────────────────────────" if i < len(user_search_state[user_id]['results'])-1 else "")
                for i, entry in enumerate(user_search_state[user_id]['results'][:10])
            ]
            msg_lines.append("Send a number to download, 'all' to download all, or use the 'discard' button to cancel.")
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = []
            if len(user_search_state[user_id]['results']) > 10:
                keyboard.append([InlineKeyboardButton("Next page →", callback_data="next_page")])
            keyboard.append([InlineKeyboardButton("Discard", callback_data="discard_search")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"*Select a song by number:*\n\n" + "\n".join(msg_lines),
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        elif 'open.spotify.com' in message_text and '/track/' in message_text:
            success = await download_spotify_track_fast(message_text, update, processing_msg)
            if success:
                await processing_msg.edit_text(
                    "✅ *Done!* \n\nSend another link! 🎧",
                    parse_mode='Markdown'
                )
        elif 'youtube.com' in message_text or 'youtu.be' in message_text:
            success = await download_youtube_music_fast(message_text, update, processing_msg)
            if success:
                await processing_msg.edit_text(
                    "✅ *Done!* \n\nSend another link! 🎧",
                    parse_mode='Markdown'
                )
        else:
            await search_and_select_youtube(update, processing_msg, message_text)
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await processing_msg.edit_text(
            "❌ *Error* \n\nPlease try a different link.",
            parse_mode='Markdown'
        )

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handles user reply with song number
    user_id = update.effective_user.id
    if user_id in user_search_state:
        state = user_search_state[user_id]
        results = state['results']
        page = state['page']
        page_size = 10
        start = page * page_size
        end = start + page_size
        page_results = results[start:end]
        text = update.message.text.strip().lower()
        try:
            # Download all
            if text == 'all':
                for entry in results:
                    url = entry.get('url')
                    name = entry.get('title', 'Unknown')
                    artist = entry.get('uploader', 'Unknown Artist')
                    duration = int(entry.get('duration', 0) or 0)
                    msg = await update.message.reply_text(
                        f"⬇️ Downloading `{name}` by {artist} ({duration//60}:{duration%60:02d} min)...",
                        parse_mode='Markdown'
                    )
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                        output_path = tmp_file.name
                    success = await run_in_executor(download_audio_fast, url, output_path)
                    if success:
                        with open(output_path, 'rb') as audio_file:
                            await update.message.reply_audio(
                                audio=audio_file,
                                title=name[:64],
                                performer=artist[:64],
                                caption=f"🎵 *{name}* by {artist}",
                                parse_mode='Markdown',
                                filename=f"{sanitize_filename(artist)} - {sanitize_filename(name)}.mp3"
                            )
                        try:
                            os.unlink(output_path)
                        except:
                            pass
                    await msg.edit_text(
                        f"✅ *Done!* \n\nSend another name or link! 🎧",
                        parse_mode='Markdown'
                    )
                del user_search_state[user_id]
                return
            # Discard
            if text == 'discard':
                del user_search_state[user_id]
                await update.message.reply_text("Search discarded. Send a new song or artist name.")
                return
            # Next page
            if text.isdigit():
                number = int(text)
                if number == len(page_results)+1 and end < len(results):
                    state['page'] += 1
                    processing_msg = await update.message.reply_text("Next page...", parse_mode='Markdown')
                    await send_search_page(update, processing_msg, user_id)
                    return
                # Download single
                if 1 <= number <= len(page_results):
                    entry = page_results[number-1]
                    url = entry.get('url')
                    name = entry.get('title', 'Unknown')
                    artist = entry.get('uploader', 'Unknown Artist')
                    duration = int(entry.get('duration', 0) or 0)
                    msg = await update.message.reply_text(
                        f"⬇️ Downloading `{name}` by {artist} ({duration//60}:{duration%60:02d} min)...",
                        parse_mode='Markdown'
                    )
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                        output_path = tmp_file.name
                    success = await run_in_executor(download_audio_fast, url, output_path)
                    if success:
                        with open(output_path, 'rb') as audio_file:
                            await update.message.reply_audio(
                                audio=audio_file,
                                title=name[:64],
                                performer=artist[:64],
                                caption=f"🎵 *{name}* by {artist}",
                                parse_mode='Markdown',
                                filename=f"{sanitize_filename(artist)} - {sanitize_filename(name)}.mp3"
                            )
                        try:
                            os.unlink(output_path)
                        except:
                            pass
                    await msg.edit_text(
                        f"✅ *Done!* \n\nSend another name or link! 🎧",
                        parse_mode='Markdown'
                    )
                    del user_search_state[user_id]
                    return
                else:
                    await update.message.reply_text(
                        "❌ Invalid number. Please reply with a valid song number.",
                        parse_mode='Markdown'
                    )
                    return
        except Exception as e:
            logger.error(f"Error handling reply: {e}")
            await update.message.reply_text(
                "❌ Error processing your selection.",
                parse_mode='Markdown'
            )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fast error handling"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ *Quick Error* \n\nSomething went wrong. Try again! ⚡",
            parse_mode='Markdown'
        )

def main():
    """Start the optimized bot"""
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_reply))
    from telegram.ext import CallbackQueryHandler
    async def discard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_search_state.pop(user_id, None)
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Search discarded. Send a new song or artist name.")

    async def next_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in user_search_state:
            user_search_state[user_id]['page'] += 1
            await update.callback_query.answer()
            await send_search_page(update, update.callback_query.message, user_id)

    async def prev_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in user_search_state and user_search_state[user_id]['page'] > 0:
            user_search_state[user_id]['page'] -= 1
            await update.callback_query.answer()
            await send_search_page(update, update.callback_query.message, user_id)

    application.add_handler(CallbackQueryHandler(discard_callback, pattern="^discard_search$"))
    application.add_handler(CallbackQueryHandler(next_page_callback, pattern="^next_page$"))
    application.add_handler(CallbackQueryHandler(prev_page_callback, pattern="^prev_page$"))
    application.add_error_handler(error_handler)
    print("🎵 FAST Music Downloader Bot is running...")
    print("⚡ Optimized for speed!")
    print("📍 Send /start to your bot on Telegram")
    print("⏹️ Press Ctrl+C to stop the bot")
    application.run_polling()

if __name__ == '__main__':
    main()
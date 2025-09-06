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

# Spotify API credentials
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET')

# Set up Spotify client
def setup_spotify_client():
    """Set up and return Spotify client"""
    auth_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
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
        'default_search': 'ytsearch10',  # Search top 10 results
        'noplaylist': True,
    }

    try:
        logger.warning(f"Starting YouTube search for query: '{query}'")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch10:{query}", download=False)
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
        logger.info(f"[Timing] YouTube search took {time.time() - step_start:.2f} seconds.")
        if not youtube_url:
            await processing_msg.edit_text(
                f"❌ *Sorry, I couldn't find* \n`{query}`",
                parse_mode='Markdown'
            )
            return False
        await processing_msg.edit_text(
            f"⬇️ Downloading `{track_info['name']}` by {track_info['artist']}... Please wait, this may take a while.",
            parse_mode='Markdown'
        )
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
        tracks = playlist['tracks']['items']
        total = len(tracks)
        track_files = []
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


📝 *Just send me a link!*

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
            'default_search': 'ytsearch10',
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch10:{query}", download=False)
        logger.warning(f"yt-dlp raw info for search: {info}")
        if not info or 'entries' not in info or not info['entries']:
            await processing_msg.edit_text(
                f"❌ No results found for `{query}`.",
                parse_mode='Markdown'
            )
            return None
        results = info['entries']
        msg_text = "\n".join([
            f"{i+1}. {entry.get('title', 'Unknown')} | {entry.get('uploader', 'Unknown Artist')} | {int(entry.get('duration', 0))//60}:{int(entry.get('duration', 0))%60:02d} min"
            for i, entry in enumerate(results)
        ])
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[InlineKeyboardButton("Discard", callback_data="discard_search")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await processing_msg.edit_text(
            f"*Select a song by number:*\n\n{msg_text}\n\nReply with the number of the song you want to download.",
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
    user = update.effective_user
    message_text = update.message.text
    logger.info(f"Received message from {user.first_name}: {message_text}")
    # Quick link check
    if not any(domain in message_text for domain in ['open.spotify.com', 'youtube.com', 'youtu.be', 'music.youtube.com']):
        # If user has search results and sends a number, treat as selection
        if 'yt_search_results' in context.user_data and message_text.strip().isdigit():
            number = int(message_text.strip())
            results = context.user_data['yt_search_results']
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
                # Download and send
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
                # Clear search results
                context.user_data.pop('yt_search_results', None)
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
        results = await search_and_select_youtube(update, processing_msg, message_text)
        if results:
            context.user_data['yt_search_results'] = results
        return
    
    # Quick processing message
    processing_msg = await update.message.reply_text(
        "⚡ *Processing...* \n\nThis will be fast! 🚀",
        parse_mode='Markdown'
    )
    try:
        # Fast processing based on link type
        if 'open.spotify.com' in message_text and '/playlist/' in message_text:
            success = await download_spotify_playlist_fast(message_text, update, processing_msg)
            if success:
                await processing_msg.edit_text(
                    "✅ *Done!* \n\nSend another link! 🎧",
                    parse_mode='Markdown'
                )
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
            # Treat as search query
            results = await search_and_select_youtube(update, processing_msg, message_text)
            if results:
                # Store results in context for next message
                context.user_data['yt_search_results'] = results
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await processing_msg.edit_text(
            "❌ *Error* \n\nPlease try a different link.",
            parse_mode='Markdown'
        )

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handles user reply with song number
    if 'yt_search_results' in context.user_data:
        try:
            number = int(update.message.text.strip())
            results = context.user_data['yt_search_results']
            if 1 <= number <= len(results):
                entry = results[number-1]
                url = entry.get('url')
                name = entry.get('title', 'Unknown')
                artist = entry.get('uploader', 'Unknown Artist')
                duration = entry.get('duration', 0)
                msg = await update.message.reply_text(
                    f"⬇️ Downloading `{name}` by {artist} ({duration//60}:{duration%60:02d} min)...",
                    parse_mode='Markdown'
                )
                # Download and send
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
                # Clear search results
                context.user_data.pop('yt_search_results', None)
            else:
                await update.message.reply_text(
                    "❌ Invalid number. Please reply with a valid song number.",
                    parse_mode='Markdown'
                )
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
        context.user_data.pop('yt_search_results', None)
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Search discarded. Send a new song or artist name.")
    application.add_handler(CallbackQueryHandler(discard_callback, pattern="^discard_search$"))
    application.add_error_handler(error_handler)
    print("🎵 FAST Music Downloader Bot is running...")
    print("⚡ Optimized for speed!")
    print("📍 Send /start to your bot on Telegram")
    print("⏹️ Press Ctrl+C to stop the bot")
    application.run_polling()

if __name__ == '__main__':
    main()
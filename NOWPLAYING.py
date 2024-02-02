import os
import io
import time
import discord
import aiohttp 
import requests
import tempfile
import urllib.parse
from io import BytesIO
from discord import Option
from datetime import datetime, timedelta
from discord.ext import tasks, commands


# Discord bot token and Emby server details
discord_bot_token = os.getenv('NOWPLAYING_DISCORD_BOT_TOKEN')
emby_server_ip = '192.168.4.101'
emby_server_port = '8096'
api_key = os.getenv('EMBY_API_BOT_KEY')
emby_thread_channel_id = int(os.getenv('EMBY_THREAD_CHANNEL'))  # Fetch the channel ID from environment variable


# Initialize Discord bot with intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True          # Necessary for reading message content
intents.reactions = True                # If you want to track reactions
intents.emojis_and_stickers = False     # If you want to track emojis and stickers
intents.integrations = True             # If you want to track integrations
intents.webhooks = True                 # If you want to track webhooks
intents.invites = False                 # If you want to track invites
intents.voice_states = False            # If you want to track voice state changes
intents.presences = True                # If you want to track user presences (e.g., online status)
intents.typing = False                  # Typically not needed, can be spammy

bot = commands.Bot(command_prefix='/', intents=intents)

# User-specific configurations
users_watch = ['tim','jeffery']  # List of usernames to watch (case-insensitive)
users_ignore = ['adult']  # List of usernames to ignore (case-insensitive)

# Dictionary to keep track of the last item and last message for each user
last_user_info = {
    user.lower(): {
        'last_item_id': None, 
        'last_embed_message': None,  # This will track the message with the embed
        'last_image_message': None  # This will track the separate image message
    } for user in users_watch
}
last_global_nothing_message = None

@bot.event
async def on_ready():
    global last_item_id
    print(f'{bot.user.name} has connected to Discord!')
    channel = bot.get_channel(emby_thread_channel_id)  # Use the channel ID from environment variable
    thread = discord.utils.get(channel.threads, name="Now Playing Updates")
    if thread is None:
        thread = await channel.create_thread(name="Now Playing Updates", type=discord.ChannelType.private_thread)
        print("Created new thread for updates.")
    else:
        print("Found existing thread.")

    # Initialize bot.last_now_playing_message
    bot.last_now_playing_message = None

    messages = await thread.history(limit=200).flatten()
    for message in messages:
        if message.author == bot.user:
            await message.delete()
            bot.last_now_playing_message = message  # Update the last bot message

    bot.now_playing_thread = thread
    now_playing_check.start()



@bot.slash_command(name='q_artist', description='Query artist information from Emby server')
async def query_artist(ctx, artist_name: Option(str, "Enter the artist's name")):
    emby_server_ip = '192.168.4.101'  # Replace with your Emby server IP
    emby_server_port = '8096'  # Replace with your Emby server port
    api_key = os.getenv('EMBY_API_BOT_KEY')  # Replace with your API key

    # Emby API endpoint to search for an artist
    search_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Artists?SearchTerm={artist_name}&api_key={api_key}"
    response = requests.get(search_url)
    if response.status_code == 200:
        artist_data = response.json()
        if artist_data['Items']:
            # Assuming the artist data contains an image
            artist_id = artist_data['Items'][0]['Id']
            image_tag = artist_data['Items'][0]['ImageTags'].get('Primary', '')
            if image_tag:
                image_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{artist_id}/Images/Primary?tag={image_tag}&api_key={api_key}"
                embed = discord.Embed(title=f"Artist Information: {artist_name}")
                embed.set_thumbnail(url=image_url)
                await ctx.respond(embed=embed)
            else:
                await ctx.respond(f"Artist found, but no image available for {artist_name}.")
        else:
            await ctx.respond(f"No artist found with the name {artist_name}.")
    else:
        await ctx.respond(f"Failed to retrieve data for artist '{artist_name}'.")


@tasks.loop(seconds=10)
async def now_playing_check():
    global last_user_info, last_global_nothing_message

    print("Checking now playing...")

    try:
        response = requests.get(f'http://{emby_server_ip}:{emby_server_port}/Sessions', headers={'X-Emby-Token': api_key})
        if response.status_code != 200:
            print(f"Failed to retrieve 'Now Playing' information from Emby. Status Code: {response.status_code}")
            return

        now_playing_data = response.json()
        active_users = {}

        for session in now_playing_data:
            username = session.get('UserName', '').lower()
            if username in users_ignore or username not in users_watch:
                continue

            item = session.get('NowPlayingItem')
            if item:
                print(f"Now Playing Item for user {username}: {item}")  # Uncomment to Print Item details for debugging
                media_type = item.get('Type').lower()
                item_id = item.get('Id')
                active_users[username] = item_id
                if last_user_info.get(username, {}).get('last_item_id') != item_id:
                    await handle_media(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username, media_type)

        # Handle "Nothing Playing" if no active users are detected
        if not active_users:
            if not last_global_nothing_message:
                last_global_nothing_message = await send_nothing_playing_message()
                print("Displayed 'Nothing Playing' message.")
        else:
            if last_global_nothing_message:
                await last_global_nothing_message.delete()
                last_global_nothing_message = None
                print("Removed 'Nothing Playing' message.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")

async def clear_all_bot_messages():
    global last_user_info, bot

    # Iterate through all users and clear messages
    for username, user_info in last_user_info.items():
        if user_info.get('last_embed_message'):
            try:
                await user_info['last_embed_message'].delete()
            except discord.NotFound:
                pass
            user_info['last_embed_message'] = None

        if user_info.get('last_image_message'):
            try:
                await user_info['last_image_message'].delete()
            except discord.NotFound:
                pass
            user_info['last_image_message'] = None

    # Also clear the global "Nothing Playing" message if it exists
    if hasattr(bot, 'last_global_nothing_message') and bot.last_global_nothing_message:
        try:
            await bot.last_global_nothing_message.delete()
        except discord.NotFound:
            pass
        bot.last_global_nothing_message = None

    print("Cleared all bot messages.")

async def handle_nothing(username):
    global last_user_info, bot  # Ensure 'bot' is accessible

    # Check and initialize user info if not present
    if username not in last_user_info:
        last_user_info[username] = {
            'last_item_id': None,
            'last_embed_message': None,  # Updated to use last_embed_message
        }

    # Path to the image file
    image_path = './ASSETS/Nothing_Playing.jpg'
    file = discord.File(image_path, filename='Nothing_Playing.jpg')

    # Create an embed with the image
    embed = discord.Embed(title="\u200B", color=discord.Color.blue())  # Invisible character as title
    embed.set_image(url="attachment://Nothing_Playing.jpg")

    # Delete the previous embed message for the user, if any
    if 'last_embed_message' in last_user_info[username] and last_user_info[username]['last_embed_message']:
        try:
            await last_user_info[username]['last_embed_message'].delete()
            print(f"Deleted last embed message for {username}.")
        except discord.NotFound:
            print(f"No previous embed message found for {username}.")

    # Debug output
    print("Sending 'Nothing Playing' message to thread:", bot.now_playing_thread.id)

    # Send the new message and update last_user_info
    try:
        new_embed_message = await bot.now_playing_thread.send(embed=embed, file=file)
        last_user_info[username]['last_embed_message'] = new_embed_message  # Update to store the new embed message
        last_user_info[username]['last_item_id'] = None
        print(f"Sent 'Nothing Playing' message for {username}.")
    except Exception as e:
        print(f"Error sending 'Nothing Playing' message for {username}:", str(e))

async def send_nothing_playing_message():
    global last_user_info, last_global_nothing_message, bot  # Ensure 'bot' is accessible

    # Clear all messages from the bot before posting 'Nothing Playing'
    async for message in bot.now_playing_thread.history(limit=10):  # Adjust the limit based on your needs
        if message.author == bot.user and not message.is_system():
            await message.delete()

    # Prepare the 'Nothing Playing' image and embed
    image_path = './ASSETS/Nothing_Playing.jpg'
    file = discord.File(image_path, filename='Nothing_Playing.jpg')
    embed = discord.Embed(title="\u200B", color=discord.Color.blue())  # Invisible character as title
    embed.set_image(url="attachment://Nothing_Playing.jpg")

    # Clear references to previous messages stored in last_user_info
    for username, user_info in last_user_info.items():
        user_info['last_embed_message'] = None
        user_info['last_image_message'] = None  # Assuming you have this reference in your user_info

    # Send the global "Nothing Playing" message and update the reference
    last_global_nothing_message = await bot.now_playing_thread.send(embed=embed, file=file)
    print(f"Sent 'Nothing Playing' message. Message ID: {last_global_nothing_message.id}")

    # Update the bot's status to "Nothing"
    await bot.change_presence(activity=discord.Game(name="Nothing"))
    print("Updated bot status to 'Nothing'.")

    return last_global_nothing_message


async def clear_nothing_playing_message():
    global last_global_nothing_message, bot

    if hasattr(bot, 'last_global_nothing_message') and bot.last_global_nothing_message:
        try:
            await bot.last_global_nothing_message.delete()
            print("Deleted 'Nothing Playing' message.")
        except discord.NotFound:
            print("Nothing Playing message already deleted.")
        bot.last_global_nothing_message = None


async def handle_nothing_playing(current_active_users):
    global last_user_info, last_global_nothing_message, bot

    print(f"Handling 'Nothing Playing'. Current active users: {current_active_users}")

    if not current_active_users:
        # Send the 'Nothing Playing' message which now also clears all bot messages before posting
        last_global_nothing_message = await send_nothing_playing_message()
        print(f"Sent 'Nothing Playing' message. Message ID: {last_global_nothing_message.id}")
    else:
        # If there are active users but the 'Nothing Playing' message is still showing, delete it
        if last_global_nothing_message:
            try:
                await last_global_nothing_message.delete()
                print("Deleted 'Nothing Playing' message.")
            except discord.NotFound:
                print("Nothing Playing message already deleted.")
            finally:
                last_global_nothing_message = None  # Clear the reference



async def clear_bot_messages_in_channel(channel):
    # This function will delete all messages sent by the bot in a specified channel
    deleted_count = 0  # Counter for deleted messages
    async for message in channel.history(limit=200):  # Adjust limit as needed
        if message.author == bot.user:
            try:
                await message.delete()
                deleted_count += 1
            except discord.NotFound:
                # If the message is already deleted, just continue
                continue
    print(f"Cleared {deleted_count} bot messages in the channel.")
    
async def handle_media(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username, media_type):
    global last_user_info

    print(f"Handling media for user {username}. Media type: {media_type}")

    current_time = datetime.utcnow()
    media_type = media_type.lower()

    # Check if the media type is 'nothing' or if the item has stopped/restarted
    if media_type == 'nothing' or last_user_info[username]['last_item_id'] != item_id:
        # Update the timestamp regardless of the media type
        last_user_info[username]['last_update_time'] = current_time

        # Delete both embed and image messages for the user
        if 'last_embed_message' in last_user_info[username] and last_user_info[username]['last_embed_message']:
            try:
                await last_user_info[username]['last_embed_message'].delete()
            except discord.NotFound:
                pass
            last_user_info[username]['last_embed_message'] = None

        if 'last_image_message' in last_user_info[username] and last_user_info[username]['last_image_message']:
            try:
                await last_user_info[username]['last_image_message'].delete()
            except discord.NotFound:
                pass
            last_user_info[username]['last_image_message'] = None

        # Determine the type of media and call the appropriate handler
        if media_type == 'movie':
            await handle_movie(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username)
        elif media_type == 'episode':
            await handle_episode(bot, item, emby_server_ip, emby_server_port, api_key, username)
        elif media_type == 'audio':
            await handle_audio(bot, item, emby_server_ip, emby_server_port, api_key, username)
        elif media_type == 'musicvideo':
            await handle_music_video(bot, item, emby_server_ip, emby_server_port, api_key, username)
        elif media_type == 'audiobook':
            await handle_audio_book(bot, item, username)
        else:
            await handle_generic_media(bot, item, username, media_type)

        # Update the last item ID for this user
        last_user_info[username]['last_item_id'] = item_id
    else:
        # If the same item is playing and it hasn't been long enough, don't update
        last_update_time = last_user_info[username].get('last_update_time', datetime.utcfromtimestamp(0))
        if current_time - last_update_time < timedelta(seconds=10):
            return


async def handle_episode(bot, item, emby_server_ip, emby_server_port, api_key, username):
    global last_user_info

    # Call this function to clear the "Nothing Playing" message before proceeding
    await clear_nothing_playing_message()

    # Initialize last_user_info for the user if not already done
    if username not in last_user_info:
        last_user_info[username] = {
            'last_item_id': None,
            'last_embed_message': None,  # For tracking the latest message
        }

    series_title = item.get('SeriesName', 'Unknown Series')
    title = item.get('Name')
    episode_number = item.get('IndexNumber', 'Unknown Episode')
    season_number = item.get('ParentIndexNumber', 'Unknown Season')

    # Extract the show directory path from the network share
    item_path = item.get('Path')
    show_directory = os.path.dirname(os.path.dirname(item_path))  # Go up two levels to get to the show directory

    # Check if the folder.jpg exists, if not use Series_Missing.jpg
    folder_image_path = os.path.join(show_directory, 'folder.jpg')
    if os.path.exists(folder_image_path):
        file = discord.File(folder_image_path, filename='folder_image.jpg')
    else:
        file = discord.File('./ASSETS/Series_Missing.jpg', filename='Series_Missing.jpg')

    embed_title = f"{series_title} - S{season_number:02}E{episode_number:02}: {title}"
    overview = item.get('Overview', 'No overview available')
    embed = discord.Embed(title=embed_title, description=f"**Overview:** {overview}", color=discord.Color.blue())
    embed.set_thumbnail(url="attachment://folder_image.jpg" if os.path.exists(folder_image_path) else "attachment://Series_Missing.jpg")

    # Update the bot's status message
    await bot.change_presence(activity=discord.Game(name=embed_title))
    
    # Delete the previous embed message for the user, if any
    if 'last_embed_message' in last_user_info[username] and last_user_info[username]['last_embed_message']:
        try:
            await last_user_info[username]['last_embed_message'].delete()
            print(f"Deleted last embed message for {username} (episode).")
        except discord.NotFound:
            print(f"No previous message found to delete for {username}.")

    # Send the new embed message and update last_user_info
    new_embed_message = await bot.now_playing_thread.send(embed=embed, file=file)
    last_user_info[username]['last_embed_message'] = new_embed_message
    print(f"Sent new episode message for {username}.")

    # For sending the episode's primary image as a separate message after the embed
    # Assume the primary image URL is constructed similarly to how we've done before
    episode_primary_image_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{item['Id']}/Images/Primary?api_key={api_key}"
    async with aiohttp.ClientSession() as session:
        async with session.get(episode_primary_image_url) as response:
            if response.status == 200:
                image_data = await response.read()
                await bot.now_playing_thread.send(file=discord.File(BytesIO(image_data), filename="episode_primary_image.jpg"))

async def handle_movie(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username):
    global last_user_info

    # Call this function to clear the "Nothing Playing" message before proceeding
    await clear_nothing_playing_message()

    # Ensure the user info structure is initialized properly
    if username not in last_user_info:
        last_user_info[username] = {
            'last_item_id': None,
            'last_update_time': datetime.min,
            'last_embed_message': None,
            'last_image_message': None,  # For tracking the latest primary image message
        }

    title = item.get('Name')
    year = item.get('ProductionYear', 'Unknown Year')

    # Construct the primary image URL with the item_id
    primary_image_url = f'http://{emby_server_ip}:{emby_server_port}/emby/Items/{item_id}/Images/Primary?api_key={api_key}'
    backdrop_image_url = f'http://{emby_server_ip}:{emby_server_port}/emby/Items/{item_id}/Images/Backdrop/0?api_key={api_key}'

    async with aiohttp.ClientSession() as session:
        # Fetch the primary image
        primary_image_response = await session.get(primary_image_url)
        if primary_image_response.status == 200:
            primary_image_data = BytesIO(await primary_image_response.read())
            primary_image_data.seek(0)
            primary_file = discord.File(fp=primary_image_data, filename='primary_image.jpg')
            primary_image_url = "attachment://primary_image.jpg"
        else:
            primary_file = discord.File('./ASSETS/Series_Missing.jpg', filename='Series_Missing.jpg')
            primary_image_url = "attachment://Series_Missing.jpg"

        embed = discord.Embed(title=f"{title} ({year})", description=item.get('Overview', 'No overview available'), color=discord.Color.blue())
        embed.set_thumbnail(url=primary_image_url)

        # Delete the previous embed message for the user, if any
        if 'last_embed_message' in last_user_info[username] and last_user_info[username]['last_embed_message']:
            try:
                await last_user_info[username]['last_embed_message'].delete()
            except discord.HTTPException as e:
                print(f"Failed to delete movie embed message: {e}")
            last_user_info[username]['last_embed_message'] = None

        # Send the new embed message with the primary image thumbnail
        new_embed_message = await bot.now_playing_thread.send(embed=embed, file=primary_file)
        last_user_info[username]['last_embed_message'] = new_embed_message

        # Fetch and send the backdrop image as a separate message
        backdrop_image_response = await session.get(backdrop_image_url)
        if backdrop_image_response.status == 200:
            backdrop_image_data = BytesIO(await backdrop_image_response.read())
            backdrop_image_data.seek(0)
            backdrop_file = discord.File(fp=backdrop_image_data, filename='backdrop_image.jpg')
            new_image_message = await bot.now_playing_thread.send(file=backdrop_file)
            last_user_info[username]['last_image_message'] = new_image_message  # Track the new image message

    # Update the bot's status message
    new_status = f"{title} ({year})"
    await bot.change_presence(activity=discord.Game(name=new_status))
    print(f"Updated bot status to: {new_status}")
    
async def handle_audio(bot, item, emby_server_ip, emby_server_port, api_key, username):
    global last_user_info

    # Initialize last_user_info for the user if not already done
    if username not in last_user_info:
        last_user_info[username] = {
            'last_item_id': None,
            'last_embed_message': None,
            'last_image_message': None
        }

    # Extract details from the item
    title = item.get('Name', 'Unknown Title')
    artists = item.get('Artists', ['Unknown Artist'])
    artist_name = artists[0] if artists else 'Unknown Artist'
    album = item.get('Album', 'Unknown Album')
    album_id = item.get('AlbumId')  # Ensuring album_id is extracted from the item
    year = item.get('ProductionYear', 'Unknown Year')  # Extracting the year

    # Prepare to fetch artist thumbnail
    artist_thumbnail_file = None
    artist_id = item.get('ArtistItems', [{}])[0].get('Id', None)  # Safely getting the artist ID
    if artist_id:
        artist_thumbnail_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{artist_id}/Images/Primary?api_key={api_key}"
        async with aiohttp.ClientSession() as session:
            async with session.get(artist_thumbnail_url) as response:
                if response.status == 200:
                    artist_thumbnail_data = BytesIO(await response.read())
                    artist_thumbnail_data.seek(0)
                    artist_thumbnail_file = discord.File(artist_thumbnail_data, filename='artist_thumbnail.jpg')

    # Prepare to fetch album cover image
    album_cover_file = None
    if album_id:  # Ensure album_id is not None
        album_cover_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{album_id}/Images/Primary?api_key={api_key}"
        async with aiohttp.ClientSession() as session:
            async with session.get(album_cover_url) as response:
                if response.status == 200:
                    album_cover_data = BytesIO(await response.read())
                    album_cover_data.seek(0)
                    album_cover_file = discord.File(album_cover_data, filename='album_cover.jpg')

    # Delete previous messages if they exist
    if 'last_embed_message' in last_user_info[username] and last_user_info[username]['last_embed_message']:
        try:
            await last_user_info[username]['last_embed_message'].delete()
        except discord.NotFound:
            pass  # If the message is already deleted or not found, just pass
        last_user_info[username]['last_embed_message'] = None

    if 'last_image_message' in last_user_info[username] and last_user_info[username]['last_image_message']:
        try:
            await last_user_info[username]['last_image_message'].delete()
        except discord.NotFound:
            pass  # If the message is already deleted or not found, just pass
        last_user_info[username]['last_image_message'] = None

    # Create the embed for the audio with description formatting
    embed = discord.Embed(title=title, color=discord.Color.blue())
    embed_description = f"**Artist:** {artist_name}\n**Album:** {album}\n**Year:** {year}"
    embed.description = embed_description
    if artist_thumbnail_file:
        embed.set_thumbnail(url="attachment://artist_thumbnail.jpg")
        
    # Send the embed message with artist thumbnail
    new_embed_message = await bot.now_playing_thread.send(file=artist_thumbnail_file, embed=embed) if artist_thumbnail_file else await bot.now_playing_thread.send(embed=embed)
    last_user_info[username]['last_embed_message'] = new_embed_message

    # If album cover file is available, send it as a separate message
    if album_cover_file:
        new_image_message = await bot.now_playing_thread.send(file=album_cover_file)
        last_user_info[username]['last_image_message'] = new_image_message

    # Update the bot's status message
    await bot.change_presence(activity=discord.Game(name=f"{artist_name}: {title}"))

    

async def handle_music_video(bot, item, emby_server_ip, emby_server_port, api_key, username):
    global last_user_info

    # Call this function to clear the "Nothing Playing" message before proceeding
    await clear_nothing_playing_message()

    try:
        discord_file = None  # Ensure discord_file is defined at the start
        current_item_id = item.get('Id') if item else None
        current_time = datetime.utcnow()

        # Retrieve the last update time and item ID for the user
        last_update_time = last_user_info[username].get('last_update_time', datetime.utcfromtimestamp(0))
        last_item_id = last_user_info[username].get('last_item_id')

        if not item or (last_item_id == current_item_id and current_time - last_update_time < timedelta(seconds=10)):
            return

        # Attempt to delete previous messages if they exist
        if 'last_embed_message' in last_user_info[username] and last_user_info[username]['last_embed_message']:
            try:
                await last_user_info[username]['last_embed_message'].delete()
            except Exception as e:
                print(f"Failed to delete embed message: {e}")
        if 'last_image_message' in last_user_info[username] and last_user_info[username]['last_image_message']:
            try:
                await last_user_info[username]['last_image_message'].delete()
            except Exception as e:
                print(f"Failed to delete image message: {e}")

        full_title = item.get('Name', 'Unknown Music Video')
        artist, song_title = full_title.split(" - ", 1) if " - " in full_title else ("Unknown Artist", full_title)
        year = item.get('ProductionYear', 'Unknown Year')
        image_tag = item.get('ImageTags', {}).get('Primary', '')

        poster_image_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{current_item_id}/Images/Primary?tag={image_tag}&api_key={api_key}"

        # Update for artist_id definition based on your item structure
        artist_id = item.get('ArtistItems', [{}])[0].get('Id', '') if item.get('ArtistItems') else ''

        artist_image_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{artist_id}/Images/Primary?api_key={api_key}" if artist_id else ''

        description = f"**Artist:** {artist}\n**Title:** {song_title}\n**Year:** {year}"
        embed = discord.Embed(title="Music Video", description=description, color=discord.Color.blue())
        embed.set_image(url=poster_image_url)  # Set the main video poster as the embed image

        if artist_image_url:
            response = requests.get(artist_image_url)
            if response.status_code == 200:
                temp_dir = tempfile.mkdtemp()
                artist_image_path = os.path.join(temp_dir, 'artist_thumbnail.jpg')
                with open(artist_image_path, 'wb') as image_file:
                    image_file.write(response.content)
                discord_file = discord.File(fp=artist_image_path, filename='artist_thumbnail.jpg')
                embed.set_thumbnail(url="attachment://artist_thumbnail.jpg")
            else:
                print("Failed to download artist image.")

        new_embed_message = await bot.now_playing_thread.send(file=discord_file if discord_file else None, embed=embed)
        last_user_info[username]['last_embed_message'] = new_embed_message

        async with aiohttp.ClientSession() as session:
            async with session.get(poster_image_url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    image_bytes = io.BytesIO(image_data)
                    image_bytes.seek(0)
                    new_image_message = await bot.now_playing_thread.send(file=discord.File(fp=image_bytes, filename='primary_image.jpg'))
                    last_user_info[username]['last_image_message'] = new_image_message

        last_user_info[username]['last_item_id'] = current_item_id
        last_user_info[username]['last_update_time'] = current_time

        new_status = f"{artist} - {song_title}"
        await bot.change_presence(activity=discord.Game(name=new_status))

    except Exception as e:
        print(f"An error occurred while handling music video: {str(e)}")

    # Clean up the temporary directory after sending the message
    if discord_file:
        os.remove(artist_image_path)
        os.rmdir(temp_dir)


async def handle_audio_book(bot, item, username):
    title = item.get('Name', 'Unknown Audio Book')
    embed = discord.Embed(title=title, description="Currently listening to an audiobook.", color=discord.Color.blue())
    await update_or_send_new_message(bot, embed, username)

async def handle_generic_media(bot, item, username, media_type):
    title = item.get('Name', f'Unknown {media_type}')
    embed = discord.Embed(title=title, description=f"Currently watching/listening to {media_type}.", color=discord.Color.blue())
    await update_or_send_new_message(bot, embed, username)

async def update_or_send_new_message(bot, embed, username):
    global last_user_info

    # Check and initialize user info if not present
    if username not in last_user_info:
        last_user_info[username] = {
            'last_item_id': None,
            'last_embed_message': None,  # Ensure this is in place for new tracking
        }

    # Use last_embed_message 
    last_embed_message = last_user_info[username].get('last_embed_message')
    if last_embed_message:
        try:
            # Attempt to edit the existing embed message
            await last_embed_message.edit(embed=embed)
            print(f"Edited embed message for {username}.")
        except discord.NotFound:
            # If the message cannot be found (deleted manually, etc.), send a new one
            new_embed_message = await bot.now_playing_thread.send(embed=embed)
            last_user_info[username]['last_embed_message'] = new_embed_message
            print(f"Sent new embed message for {username} (edit failed).")
    else:
        # If there's no previous message, send a new one
        new_embed_message = await bot.now_playing_thread.send(embed=embed)
        last_user_info[username]['last_embed_message'] = new_embed_message  # Update to track this new message
        print(f"Sent new embed message for {username}.")

bot.run(discord_bot_token)
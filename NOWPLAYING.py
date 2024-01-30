import os
import discord
from discord.ext import tasks, commands
import requests
from io import BytesIO
import time

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
last_user_info = {user.lower(): {'last_item_id': None, 'last_message': None} for user in users_watch}

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
                media_type = item.get('Type').lower()
                item_id = item.get('Id')
                active_users[username] = item_id
                if last_user_info.get(username, {}).get('last_item_id') != item_id:
                    await handle_media(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username, media_type)

        # Handle users that are no longer active
        for username, user_info in list(last_user_info.items()):
            if username not in active_users and user_info['last_item_id'] is not None:
                if user_info['last_message']:
                    await user_info['last_message'].delete()
                    user_info['last_message'] = None
                user_info['last_item_id'] = None

        # Display "Nothing Playing" if no users are active
        if not active_users and not last_global_nothing_message:
            last_global_nothing_message = await handle_nothing_global()
            print("Displayed 'Nothing Playing' message.")
        elif active_users and last_global_nothing_message:
            await last_global_nothing_message.delete()
            last_global_nothing_message = None
            print("Removed 'Nothing Playing' message.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")


async def handle_nothing_playing(current_active_users):
    global last_global_nothing_message

    print(f"Handling 'Nothing Playing'. Current active users: {current_active_users}")

    # If there are no active users and no global "Nothing Playing" message
    if not current_active_users and not last_global_nothing_message:
        print("No active users. Sending 'Nothing Playing' message.")
        # Delete any existing user-specific messages
        for user_info in last_user_info.values():
            if user_info['last_message']:
                try:
                    await user_info['last_message'].delete()
                    user_info['last_message'] = None
                except discord.NotFound:
                    pass
        # Send the global "Nothing Playing" message
        await send_nothing_playing_message()
    # If there are active users and a global "Nothing Playing" message exists
    elif current_active_users and last_global_nothing_message:
        print("Active users found. Deleting 'Nothing Playing' message.")
        try:
            await last_global_nothing_message.delete()
            last_global_nothing_message = None
        except discord.NotFound:
            print("Failed to delete 'Nothing Playing' message.")


async def handle_nothing_global():
    global last_global_nothing_message

    image_path = './ASSETS/Nothing_Playing.jpg'
    file = discord.File(image_path, filename='Nothing_Playing.jpg')
    embed = discord.Embed(title="\u200B", color=discord.Color.blue())
    embed.set_image(url="attachment://Nothing_Playing.jpg")

    last_global_nothing_message = await bot.now_playing_thread.send(embed=embed, file=file)
    return last_global_nothing_message



async def delete_last_bot_message():
    if bot.last_now_playing_message:
        try:
            await bot.last_now_playing_message.delete()
            print("Deleted last message.")
        except discord.HTTPException as e:
            print(f"Failed to delete message: {e}")


async def handle_nothing(username):
    global last_user_info

    # Path to the image file
    image_path = './ASSETS/Nothing_Playing.jpg'
    file = discord.File(image_path, filename='Nothing_Playing.jpg')

    # Create an embed with the image
    embed = discord.Embed(title="\u200B", color=discord.Color.blue())  # Invisible character as title
    embed.set_image(url="attachment://Nothing_Playing.jpg")

    # Update the last message in last_user_info dictionary
    last_message = last_user_info[username]['last_message']
    if last_message:
        try:
            await last_message.delete()
        except discord.NotFound:
            pass

    last_user_info[username]['last_message'] = await bot.now_playing_thread.send(embed=embed, file=file)
    last_user_info[username]['last_item_id'] = None

async def handle_media(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username, media_type):
    global last_user_info

    print(f"Handling media for user {username}. Media type: {media_type}")

    # Convert media_type to lowercase for case-insensitive comparison
    media_type = media_type.lower()

    # Check if the current item is the same as the last one
    if last_user_info[username]['last_item_id'] == item_id:
        # No change in the item being played, no need to update
        return

    if media_type == 'movie':
        await handle_movie(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username)
    elif media_type == 'episode':
        await handle_episode(bot, item, emby_server_ip, emby_server_port, api_key, username)
    elif media_type == 'audio':
        await handle_audio(bot, item, emby_server_ip, emby_server_port, api_key, username)
    elif media_type == 'musicvideo':
        await handle_music_video(bot, item, username)
    elif media_type == 'audiobook':
        await handle_audio_book(bot, item, username)
    else:
        await handle_generic_media(bot, item, username, media_type)

    # Update the last item ID for this user
    last_user_info[username]['last_item_id'] = item_id



async def handle_episode(bot, item, emby_server_ip, emby_server_port, api_key, username):
    series_title = item.get('SeriesName', 'Unknown Series')
    title = item.get('Name')
    episode_number = item.get('IndexNumber', 'Unknown Episode')
    season_number = item.get('ParentIndexNumber', None)

    # Extract the show directory path from the network share
    item_path = item.get('Path')
    show_directory = os.path.dirname(os.path.dirname(item_path))  # Go up two levels to get to the show directory
    folder_image_path = os.path.join(show_directory, 'folder.jpg')

    # Check if the folder.jpg exists, if not use Series_Missing.jpg
    if os.path.exists(folder_image_path):
        file = discord.File(folder_image_path, filename='folder_image.jpg')
    else:
        file = discord.File('./ASSETS/Series_Missing.jpg', filename='Series_Missing.jpg')

    embed_title = f"{series_title}\n(S{season_number:02d}E{episode_number:02d}) {title}"
    embed = discord.Embed(title=embed_title, color=discord.Color.blue())
    overview = item.get('Overview', 'No overview available')
    embed.add_field(name="Overview", value=overview, inline=False)
    embed.set_image(url="attachment://folder_image.jpg" if os.path.exists(folder_image_path) else "attachment://Series_Missing.jpg")

    # Update the last message for the user
    last_message = last_user_info[username]['last_message']
    if last_message:
        try:
            await last_message.delete()
            print(f"Deleted last message for {username} (episode).")
        except discord.NotFound:
            pass
    last_user_info[username]['last_message'] = await bot.now_playing_thread.send(embed=embed, file=file)
    print(f"Sent new episode message for {username}.")


async def handle_audio(bot, item, emby_server_ip, emby_server_port, api_key, username):
    global last_user_info

    try:
        # If no item is playing, clear the last message and reset last_item_id.
        if not item and last_user_info[username]['last_item_id'] is not None:
            if last_user_info[username]['last_message']:
                await last_user_info[username]['last_message'].delete()
                last_user_info[username]['last_message'] = None
            last_user_info[username]['last_item_id'] = None
            return

        current_item_id = item.get('Id') if item else None

        # Skip if the current item is the same as the last one.
        if last_user_info[username]['last_item_id'] == current_item_id:
            return

        title = item.get('Name', 'Unknown Title')
        album_artist = item.get('AlbumArtist', 'Unknown Artist')
        album = item.get('Album', 'Unknown Album')
        image_tag = item.get('ImageTags', {}).get('Primary')

        # Construct the image URL with the API key.
        image_url = ""
        if image_tag:
            image_url = f"http://{emby_server_ip}:{emby_server_port}/emby/Items/{current_item_id}/Images/Primary?tag={image_tag}&api_key={api_key}"

        # Create the embed.
        description = f"**Title:** {title}\n**Album Artist:** {album_artist}\n**Album:** {album}"
        embed = discord.Embed(title="Audio", description=description, color=discord.Color.blue())

        if image_url:
            # Attempt to download and attach the image.
            response = requests.get(image_url)
            if response.status_code == 200:
                with BytesIO(response.content) as image_io:
                    image_io.seek(0)
                    discord_file = discord.File(fp=image_io, filename='image.jpg')
                    embed.set_image(url="attachment://image.jpg")
                    await update_or_send_new_message(bot, embed, username, file=discord_file)
            else:
                await update_or_send_new_message(bot, embed, username)
        else:
            await update_or_send_new_message(bot, embed, username)

        last_user_info[username]['last_item_id'] = current_item_id

    except Exception as e:
        print(f"An error occurred while handling audio: {str(e)}")


async def handle_music_video(bot, item, username):
    global last_user_info

    try:
        # If no item is playing, clear the last message and reset last_item_id.
        if not item and last_user_info[username]['last_item_id'] is not None:
            if last_user_info[username]['last_message']:
                await last_user_info[username]['last_message'].delete()
                last_user_info[username]['last_message'] = None
            last_user_info[username]['last_item_id'] = None
            return

        current_item_id = item.get('Id') if item else None

        # Skip if the current item is the same as the last one.
        if last_user_info[username]['last_item_id'] == current_item_id:
            return

        title = item.get('Name', 'Unknown Music Video')
        artist = ", ".join(item.get('Artists', ['Unknown Artist']))
        album = item.get('Album', 'Unknown Album')
        year = item.get('ProductionYear', 'Unknown Year')

        # Create a description for the embed.
        description = f"Artist: {artist}\nAlbum: {album}\nYear: {year}\nTitle: {title}"
        embed = discord.Embed(title="Music Video", description=description, color=discord.Color.blue())

        # Send the embed message
        await update_or_send_new_message(bot, embed, username)

        last_user_info[username]['last_item_id'] = current_item_id

    except Exception as e:
        print(f"An error occurred while handling music video: {str(e)}")



async def handle_audio_book(bot, item, username):
    title = item.get('Name', 'Unknown Audio Book')
    embed = discord.Embed(title=title, description="Currently listening to an audiobook.", color=discord.Color.blue())
    await update_or_send_new_message(bot, embed, username)

async def handle_generic_media(bot, item, username, media_type):
    title = item.get('Name', f'Unknown {media_type}')
    embed = discord.Embed(title=title, description=f"Currently watching/listening to {media_type}.", color=discord.Color.blue())
    await update_or_send_new_message(bot, embed, username)

async def update_or_send_new_message(bot, embed, username):
    last_message = last_user_info[username]['last_message']
    if last_message:
        try:
            await last_message.edit(embed=embed)
            print(f"Edited message for {username}.")
        except discord.NotFound:
            last_user_info[username]['last_message'] = await bot.now_playing_thread.send(embed=embed)
            print(f"Sent new message for {username} (edit failed).")
    else:
        last_user_info[username]['last_message'] = await bot.now_playing_thread.send(embed=embed)
        print(f"Sent new message for {username}.")


async def send_nothing_playing_message():
    global last_global_nothing_message
    image_path = './ASSETS/Nothing_Playing.jpg'
    file = discord.File(image_path, filename='Nothing_Playing.jpg')
    embed = discord.Embed(title="\u200B", color=discord.Color.blue())  # Invisible character as title
    embed.set_image(url="attachment://Nothing_Playing.jpg")
    last_global_nothing_message = await bot.now_playing_thread.send(embed=embed, file=file)

async def handle_movie(bot, item, emby_server_ip, emby_server_port, api_key, item_id, username):
    title = item.get('Name')
    year = item.get('ProductionYear', 'Unknown Year')
    size_bytes = item.get('Size', 0)
    size_gb = round(size_bytes / (1024 ** 3), 2)
    genres = ', '.join(item.get('Genres', ['Unknown Genre']))
    overview = item.get('Overview', 'No overview available')

    # Check if the content is adult and filter it out
    if item.get('OfficialRating', '').lower() == 'adult':
        return None, None

    # Construct the image URL with the item_id
    image_url = f'http://{emby_server_ip}:{emby_server_port}/emby/Items/{item_id}/Images/Primary?api_key={api_key}'
    image_response = requests.get(image_url)

    if image_response.status_code == 200:
        image_data = BytesIO(image_response.content)
        image_data.seek(0)
        file = discord.File(fp=image_data, filename='now_playing_image.jpg')
    else:
        print(f"Failed to download image from {image_url}. Using default image. Status Code: {image_response.status_code}")
        file = discord.File('./ASSETS/Movie_Missing.jpg', filename='Movie_Missing.jpg')

    embed = discord.Embed(title=f"{title} ({year})", description=f"**Size:** {size_gb} GB\n**Genres:** {genres}\n**Overview:** {overview}")
    embed.set_image(url="attachment://now_playing_image.jpg" if image_response.status_code == 200 else "attachment://Movie_Missing.jpg")

    # Update the last message for the user
    last_message = last_user_info[username]['last_message']
    if last_message:
        try:
            await last_message.delete()
        except discord.HTTPException as e:
            print(f"Failed to delete message: {e}")

    last_user_info[username]['last_message'] = await bot.now_playing_thread.send(embed=embed, file=file)


    return None, None


bot.run(discord_bot_token)
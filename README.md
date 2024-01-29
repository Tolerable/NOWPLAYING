# NOWPLAYING Discord Bot

`NOWPLAYING` is a Discord bot designed to display real-time now playing information from an Emby server in a designated Discord channel. It allows users to see the details of the media currently being played on the Emby server, enhancing the community's media sharing and viewing experience.

## Features

- Real-time updates of media playback from Emby server.
- Displays detailed information including titles, artists, albums, and images.
- Supports various media types including movies, episodes, audio, and music videos.
- Configurable to monitor specific user activities and ignore others.
- Automated messages for "Nothing Playing" scenarios.

## Setup and Installation

1. Clone the repository to your local machine.
2. Install the required Python packages.
3. Set up necessary environment variables for Discord bot token, Emby server IP, port, and API key.
4. Configure the Discord channel ID where updates will be posted.
5. Run the script to start the bot.

## Usage

Once set up, the bot periodically checks the Emby server for current playback sessions and posts updates in the designated Discord channel. Users can see at a glance what media is currently being played and who is watching it.

## Running the Bot

To run the bot:

```bash
python NOWPLAYING.py
```

## Authors

- **Tolerable** https://github.com/Tolerable

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.

## Acknowledgments

- Thanks to EMBY

from typing import List, Dict

from ytmusicapi import YTMusic

from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

# Initialize YTMusic (using guest mode for now to avoid requiring browser auth)
yt: YTMusic = YTMusic()

def search_youtube(query: str, limit: int = 20) -> List[Dict]:
    """
    Search YouTube Music for songs matching the query.

    Args:
        query: Search string.

    Returns:
        A list of formatted dictionaries containing track metadata.
    """
    _logger.info("External search on YouTube Music for: %s", query)
    try:
        results = yt.search(query, filter="songs", limit=limit)
        formatted_results = []
        for item in results:
            formatted_results.append({
                "id": item.get("videoId"),
                "title": item.get("title"),
                "artist": ", ".join([a.get("name") for a in item.get("artists", [])]),
                "album": item.get("album", {}).get("name"),
                "duration": item.get("duration_seconds"),
                "source_type": "youtube",
                "remote_id": item.get("videoId"),
                "is_cached": False,  # Checked against DB in main search logic
                "thumbnail": item.get("thumbnails", [{}])[-1].get("url")
            })
        return formatted_results
    except Exception:
        _logger.exception("YouTube Music API search failed")
        return []
def get_related_tracks(video_id: str, limit: int = 20) -> List[Dict]:
    """
    Fetch related tracks based on a video ID (Radio Mode).
    """
    _logger.info("Fetching related tracks for: %s", video_id)
    try:
        # get_watch_playlist returns a playlist of related videos
        watch_playlist = yt.get_watch_playlist(video_id, limit=limit)
        results = watch_playlist.get("tracks", [])
        
        formatted_results = []
        for item in results:
            # Skip the current video if it's in the results
            if item.get("videoId") == video_id:
                continue
                
            formatted_results.append({
                "id": item.get("videoId"),
                "title": item.get("title"),
                "artist": ", ".join([a.get("name") for a in item.get("artists", [])]),
                "album": item.get("album", {}).get("name"),
                "duration": item.get("duration_seconds"),
                "source_type": "youtube",
                "remote_id": item.get("videoId"),
                "thumbnail": item.get("thumbnails", [{}])[-1].get("url")
            })
        return formatted_results
    except Exception:
        _logger.exception("YouTube Music get_related_tracks failed")
        return []

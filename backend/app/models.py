from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class User(SQLModel, table=True):
    """
    User account model for both Google and password-based authentication.
    """
    id: str = Field(primary_key=True)
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    hashed_password: Optional[str] = None
    role: str = Field(default="user")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Relationships
    activities: List["UserActivity"] = Relationship(back_populates="user")
    playlists: List["Playlist"] = Relationship(back_populates="owner")

class Track(SQLModel, table=True):
    """
    Music track metadata for both local files and remote YouTube sources.
    """
    id: str = Field(primary_key=True)
    title: str = Field(index=True)
    artist: Optional[str] = Field(default=None, index=True)
    album: Optional[str] = Field(default=None, index=True)
    source_type: str  # 'local', 'youtube'
    remote_id: Optional[str] = None
    local_path: Optional[str] = None
    is_cached: bool = Field(default=False)
    duration: Optional[int] = None
    thumbnail: Optional[str] = Field(default=None)
    added_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Relationships
    activities: List["UserActivity"] = Relationship(back_populates="track")

class Playlist(SQLModel, table=True):
    """
    User-defined collection of tracks.
    """
    id: str = Field(primary_key=True)
    name: str
    owner_id: str = Field(foreign_key="user.id")
    is_offline: bool = Field(default=False)
    is_public: bool = Field(default=False)
    
    # Relationships
    owner: User = Relationship(back_populates="playlists")

class PlaylistTrack(SQLModel, table=True):
    """
    Many-to-many relationship between playlists and tracks with position.
    """
    playlist_id: str = Field(foreign_key="playlist.id", primary_key=True)
    track_id: str = Field(foreign_key="track.id", primary_key=True)
    position: int

class UserActivity(SQLModel, table=True):
    """
    Tracks user interaction with a track (likes, play count).
    """
    user_id: str = Field(foreign_key="user.id", primary_key=True)
    track_id: str = Field(foreign_key="track.id", primary_key=True)
    play_count: int = Field(default=0)
    is_liked: bool = Field(default=False)
    last_played: Optional[datetime] = None
    
    # Relationships
    user: User = Relationship(back_populates="activities")
    track: Track = Relationship(back_populates="activities")

from pydantic import BaseModel, Field
from typing import Optional, Dict

class CameraSettings(BaseModel):
    brightness: Optional[float] = Field(None, ge=0.0, le=2.0)
    contrast: Optional[float] = Field(None, ge=0.0, le=2.0)
    sharpness: Optional[float] = Field(None, ge=0.0, le=1.0)

class PlaybackCommand(BaseModel):
    level: Optional[int] = Field(None, ge=0, le=100)
    vol: Optional[int] = Field(None, ge=0, le=100)
    group: Optional[str] = None

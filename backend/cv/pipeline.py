"""GPT-4o Vision layer.

Input:  base64-encoded image (raw base64 string, no data-URI prefix).
Output: the raw structured JSON the model returns (validated downstream by the
        voxelizer). Returns None if no API key is configured or the call fails,
        so callers can fall back to the deterministic demo blueprint.
"""

import json

from backend import config

SYSTEM_PROMPT = """You are a voxel blueprint generator. Analyze the uploaded image and describe the object's 3D structure as a grid of voxels.

Respond ONLY in this JSON format:
{
  "object_name": "chair",
  "dimensions": {"x": 5, "y": 6, "z": 5},
  "complexity_score": 0.6,
  "voxels": [
    {"x": 0, "y": 0, "z": 0, "block_type": "large_slab"},
    {"x": 1, "y": 0, "z": 0, "block_type": "large_slab"}
  ]
}

Rules:
- Max grid size: 10x10x10
- Keep it pixelated and simplified — think Minecraft-style, not photorealistic
- Use block_type values: small_cube, large_slab, medium_brick
- x=left/right, y=up/down, z=front/back
- Complexity score 0.0-1.0 based on number of voxels and spatial distribution"""


def analyze_image(image_b64: str, mime: str = "image/png"):
    """Call GPT-4o Vision and return parsed JSON, or None on failure."""
    if not config.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=config.OPENAI_VISION_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Generate the voxel blueprint for this object."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=4000,
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        return _parse_json(content)
    except Exception as exc:  # network, auth, quota, parse — all fall back
        print(f"[cv.pipeline] GPT-4o Vision unavailable, using fallback: {exc}")
        return None


def _parse_json(content: str):
    content = content.strip()
    if content.startswith("```"):
        # Strip ```json ... ``` fences if present.
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)

"""
Qwen-VL Vision Model for Network Topology Recognition

This module provides vision recognition capabilities using Qwen-VL model
through DashScope SDK to identify network topology diagrams from images.
"""

import base64
import json
import os
from typing import Any, Dict, Optional
from pathlib import Path

try:
    import dashscope
except ImportError:
    dashscope = None

import logging

logger = logging.getLogger(__name__)


# System prompt for network topology recognition
TOPOLOGY_RECOGNITION_PROMPT = """You are a professional network topology analysis expert. Please carefully analyze this network topology diagram and return the detailed information in JSON format.

Requirements:
1. Identify all network devices (routers, switches, hosts, servers, etc.)
2. Identify the connections between devices
3. Identify interface and IP address information (if visible)
4. Return in standard JSON format

Please return the result in the following JSON format:
```json
{
  "topology_name": "Topology name (inferred from content)",
  "description": "Brief description of the topology",
  "devices": [
    {
      "id": "unique device identifier",
      "name": "device name",
      "type": "device type (router/switch/host/server/cloud/firewall, etc.)",
      "model": "device model (if visible)",
      "position": {
        "x": 0,
        "y": 0
      }
    }
  ],
  "links": [
    {
      "id": "unique connection identifier",
      "source_device": "source device name",
      "source_interface": "source interface name (if visible)",
      "target_device": "target device name",
      "target_interface": "target interface name (if visible)",
      "link_type": "connection type (ethernet/serial, etc.)"
    }
  ],
  "interfaces": [
    {
      "device": "device name",
      "interface": "interface name",
      "ip_address": "IP address (if visible)",
      "subnet_mask": "subnet mask (if visible)"
    }
  ],
  "summary": {
    "total_devices": 0,
    "total_links": 0,
    "device_types": {
      "router": 0,
      "switch": 0,
      "host": 0,
      "other": 0
    }
  }
}
```

Notes:
- If some information is not visible in the image, use null or empty string
- Use the labels shown in the image for device names
- Use relative coordinates for position (0-100 range)
- Ensure valid JSON format, do not include markdown code block markers
- Only return JSON, no other text explanations
"""


def encode_image_to_base64(image_path: str) -> str:
    """
    Encode an image file to base64 string.

    Args:
        image_path: Path to the image file

    Returns:
        Base64 encoded string

    Raises:
        FileNotFoundError: If image file doesn't exist
        IOError: If image file cannot be read
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    try:
        with open(path, "rb") as image_file:
            base64_string = base64.b64encode(image_file.read()).decode("utf-8")
        logger.info(f"Successfully encoded image to base64: {image_path}")
        return base64_string
    except Exception as e:
        logger.error(f"Failed to encode image: {e}")
        raise IOError(f"Failed to encode image {image_path}: {e}")


def create_data_url(base64_string: str, mime_type: str = "image/png") -> str:
    """
    Create a data URL from base64 string.

    Args:
        base64_string: Base64 encoded image string
        mime_type: MIME type of the image (default: image/png)

    Returns:
        Data URL string in format: data:[mime_type];base64,[base64_string]
    """
    return f"data:{mime_type};base64,{base64_string}"


class QwenVisionModel:
    """
    Qwen-VL vision model wrapper for network topology recognition.

    This class provides an interface to the Qwen-VL model through DashScope SDK
    for recognizing network topology diagrams from images.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "qwen-vl-max",
    ):
        """
        Initialize Qwen-VL vision model.

        Args:
            api_key: DashScope API key (if None, will load from config)
            model_name: Model name to use (default: qwen-vl-max)
                       Options: qwen-vl-max, qwen-vl-plus, qwen-vl-v1

        Raises:
            ImportError: If dashscope is not installed
            ValueError: If API key is not provided or found in config
        """
        if dashscope is None:
            raise ImportError(
                "dashscope package is not installed. "
                "Please install it: pip install dashscope"
            )

        # Load API key from environment variable if not provided
        if api_key is None:
            api_key = os.getenv("QWEN_API_KEY", "")

        if not api_key:
            raise ValueError(
                "Qwen API key is required. Please set QWEN_API_KEY environment variable "
                "or pass it to the constructor."
            )

        self.api_key = api_key
        self.model_name = model_name
        logger.info(f"QwenVisionModel initialized with model: {model_name}")

    def _supports_streaming(self) -> bool:
        """
        Check if the current model supports streaming output.

        Returns:
            True if model supports streaming (qwen3-vl-plus, qwen3-vl-flash), False otherwise
        """
        streaming_models = ["qwen3-vl-plus", "qwen3-vl-flash"]
        return self.model_name in streaming_models

    def recognize_topology_from_file(
        self,
        image_path: str,
        prompt: str = TOPOLOGY_RECOGNITION_PROMPT,
    ) -> Dict[str, Any]:
        """
        Recognize network topology from an image file.

        Args:
            image_path: Path to the image file
            prompt: Custom prompt for recognition (uses default if not provided)

        Returns:
            Dictionary containing topology information

        Raises:
            FileNotFoundError: If image file doesn't exist
            RuntimeError: If recognition fails
        """
        logger.info(f"Recognizing topology from file: {image_path}")

        # Encode image to base64
        base64_string = encode_image_to_base64(image_path)

        # Detect MIME type from file extension
        mime_type = self._get_mime_type(image_path)

        # Create data URL
        image_url = create_data_url(base64_string, mime_type)

        # Call recognition
        return self.recognize_topology_from_base64(image_url, prompt)

    def recognize_topology_from_base64(
        self,
        image_base64_or_url: str,
        prompt: str = TOPOLOGY_RECOGNITION_PROMPT,
    ) -> Dict[str, Any]:
        """
        Recognize network topology from a base64 encoded image or data URL.

        Args:
            image_base64_or_url: Base64 encoded image string or data URL
                               (format: data:image/xxx;base64,xxx)
            prompt: Custom prompt for recognition (uses default if not provided)

        Returns:
            Dictionary containing topology information

        Raises:
            RuntimeError: If recognition fails
            json.JSONDecodeError: If response is not valid JSON
        """
        logger.info("Recognizing topology from base64 image")

        # Use default prompt if not provided
        if prompt is None:
            prompt = TOPOLOGY_RECOGNITION_PROMPT

        # Prepare message for DashScope (官方格式: 使用image字段传递Data URL)
        simple_prompt = """Analyze this network topology diagram and return the result in JSON format with the following structure:
{
  "topology_name": "name",
  "description": "description",
  "devices": [{"id": "unique", "name": "device name", "type": "router/switch/host/etc", "model": "model if visible", "position": {"x": 0, "y": 0}}],
  "links": [{"id": "unique", "source_device": "name", "source_interface": "interface", "target_device": "name", "target_interface": "interface", "link_type": "ethernet/serial"}],
  "interfaces": [{"device": "name", "interface": "interface", "ip_address": "ip", "subnet_mask": "mask"}],
  "summary": {"total_devices": 0, "total_links": 0, "device_types": {"router": 0, "switch": 0, "host": 0, "other": 0}}
}
Return only valid JSON, no markdown code blocks."""

        # image_base64_or_url should already be in data URL format (data:image/xxx;base64,xxx)
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": image_base64_or_url},
                    {"text": simple_prompt}
                ]
            }
        ]

        logger.info(f"Model: {self.model_name}, Streaming: {self._supports_streaming()}")

        try:
            # Determine if we should use streaming
            use_stream = self._supports_streaming()

            if use_stream:
                # Call DashScope API with streaming
                logger.info("Using streaming mode for faster response")
                full_response = dashscope.MultiModalConversation.call(
                    model=self.model_name,
                    messages=messages,
                    api_key=self.api_key,
                    stream=True,
                )

                # Collect streaming response
                content = ""
                for chunk in full_response:
                    # Extract content from streaming chunk
                    if hasattr(chunk, 'output') and chunk.output:
                        if hasattr(chunk.output, 'choices') and chunk.output.choices:
                            choice = chunk.output.choices[0]
                            if hasattr(choice, 'message'):
                                message = choice.message
                                # Handle different message formats in streaming
                                if hasattr(message, 'content'):
                                    if message.content and len(message.content) > 0:
                                        content_item = message.content[0]
                                        if isinstance(content_item, dict):
                                            text = content_item.get('text', '')
                                        elif hasattr(content_item, 'text'):
                                            text = content_item.text
                                        else:
                                            text = str(content_item)
                                        content += text

                logger.info(f"Completed streaming, total content length: {len(content)} chars")
            else:
                # Call DashScope API without streaming
                logger.info("Using non-streaming mode")
                response = dashscope.MultiModalConversation.call(
                    model=self.model_name,
                    messages=messages,
                    api_key=self.api_key,
                )

                # Extract content from non-streaming response
                try:
                    if hasattr(response, 'output') and response.output:
                        if hasattr(response.output, 'choices') and response.output.choices:
                            if len(response.output.choices) > 0:
                                choice = response.output.choices[0]
                                if hasattr(choice, 'message') and choice.message:
                                    if hasattr(choice.message, 'content') and choice.message.content:
                                        if isinstance(choice.message.content, list) and len(choice.message.content) > 0:
                                            content_item = choice.message.content[0]
                                            if isinstance(content_item, dict):
                                                content = content_item.get('text', str(content_item))
                                            elif hasattr(content_item, 'text'):
                                                content = content_item.text
                                            else:
                                                content = str(content_item)
                except Exception as e:
                    logger.error(f"Failed to extract content: {e}")
                    content = ""

            # Parse JSON response
            # Clean up any markdown code blocks
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            try:
                topology_data = json.loads(content)
                logger.info("Successfully parsed topology JSON")
                return topology_data
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response content: {content[:500]}...")
                raise

        except Exception as e:
            logger.error(f"Failed to recognize topology: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise RuntimeError(f"Failed to recognize topology: {e}") from e

    def _get_mime_type(self, file_path: str) -> str:
        """
        Get MIME type from file extension.

        Args:
            file_path: Path to the file

        Returns:
            MIME type string
        """
        ext = Path(file_path).suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        return mime_types.get(ext, "image/png")


def create_qwen_vision_model(
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
) -> QwenVisionModel:
    """
    Factory function to create a Qwen-VL vision model instance.

    This function loads configuration from environment variables and creates
    a QwenVisionModel instance with appropriate settings.

    Args:
        api_key: DashScope API key (if None, will load from QWEN_API_KEY env var)
        model_name: Model name to use (if None, will load from QWEN_MODEL_NAME env var, default: qwen3-vl-plus)

    Returns:
        QwenVisionModel instance

    Raises:
        ImportError: If dashscope is not installed
        ValueError: If API key is not provided or found in environment

    Example:
        >>> model = create_qwen_vision_model()
        >>> topology = model.recognize_topology_from_file("topology.png")
        >>> print(topology["topology_name"])
        >>> print(f"Found {len(topology['devices'])} devices")
    """
    # Load model name from environment variable if not provided
    if model_name is None:
        model_name = os.getenv("QWEN_MODEL_NAME", "qwen3-vl-plus")

    return QwenVisionModel(api_key=api_key, model_name=model_name)

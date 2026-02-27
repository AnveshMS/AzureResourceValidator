from __future__ import annotations

import logging
from dataclasses import dataclass


try:
    from copilot import CopilotClient
except ImportError:
    CopilotClient = None

logger = logging.getLogger(__name__)


@dataclass
class MismatchContext:
    resource_name: str
    resource_type_label: str
    expected_configuration: str
    actual_configuration: str
    mismatch_reason: str


class CopilotAdapter:
    def explain_mismatch(self, context: MismatchContext) -> str:
        raise NotImplementedError

    async def cleanup(self) -> None:
        """Optional cleanup for adapter resources."""
        pass


class MockCopilotAdapter(CopilotAdapter):
    def explain_mismatch(self, context: MismatchContext) -> str:
        logger.debug(f"MockCopilotAdapter: Generating static explanation for {context.resource_name}")
        return (
            f"Configuration mismatch for '{context.resource_name}'. "
            f"Expected '{context.expected_configuration}', but found "
            f"'{context.actual_configuration}'. "
            f"Reason: {context.mismatch_reason}."
        )

    async def cleanup(self) -> None:
        """No-op cleanup for mock adapter."""
        logger.debug("MockCopilotAdapter: No resources to clean up")


class CopilotSdkAdapter(CopilotAdapter):
    def __init__(
        self,
        model: str = "gpt-5",
        github_token: str | None = None,
        copilot_cli_path: str | None = None,
    ) -> None:
        self.model = model
        self.github_token = github_token
        self.copilot_cli_path = copilot_cli_path
        self._session = None
        self._loop = None
        self._client = None

    def set_event_loop(self, loop) -> None:
        """Set the event loop for async operations."""
        self._loop = loop

    async def initialize(self) -> None:
        """Initialize client and session (must be called from event loop)."""
        if self._session is not None:
            return  # Already initialized

        logger.info("CopilotSdkAdapter: Initializing Copilot SDK client (reused across all mismatch explanations)")
        options = {
            "log_level": "error",
            "use_logged_in_user": False if self.github_token else True,
        }
        if self.github_token:
            options["github_token"] = self.github_token
            logger.debug("CopilotSdkAdapter: Using GitHub token for authentication")
        else:
            logger.debug("CopilotSdkAdapter: Using device/logged-in user authentication")
        
        if self.copilot_cli_path:
            options["cli_path"] = self.copilot_cli_path
            logger.debug(f"CopilotSdkAdapter: Using custom CLI path: {self.copilot_cli_path}")

        self._client = CopilotClient(options)
        await self._client.start()
        logger.info("CopilotSdkAdapter: Copilot SDK client started")
        
        logger.debug("CopilotSdkAdapter: Checking authentication status")
        auth_status = await self._client.get_auth_status()
        if auth_status.isAuthenticated:
            logger.info(f"CopilotSdkAdapter: Authenticated as {auth_status.login or 'user'}")
        elif self.github_token:
            logger.info("CopilotSdkAdapter: Using provided GitHub token")
        else:
            logger.error("CopilotSdkAdapter: Not authenticated and no token provided")
            raise RuntimeError("Copilot is not authenticated")

        logger.debug(f"CopilotSdkAdapter: Creating session with model: {self.model}")
        self._session = await self._client.create_session({"model": self.model})
        logger.info("CopilotSdkAdapter: Session created (will be reused for all explanations)")

    def explain_mismatch(self, context: MismatchContext) -> str:
        if CopilotClient is None:
            logger.warning("Copilot SDK not installed; falling back to mock explanation")
            return MockCopilotAdapter().explain_mismatch(context)

        if self._session is None:
            logger.warning("Copilot session not initialized; falling back to mock explanation")
            return MockCopilotAdapter().explain_mismatch(context)

        prompt = self._build_prompt(context)
        logger.debug(f"CopilotSdkAdapter: Generating AI explanation for {context.resource_name} (reused session)")
        try:
            if self._loop is None:
                raise RuntimeError("Event loop not set in adapter")
            
            result = self._loop.run_until_complete(self._run_sdk_prompt(prompt=prompt))
            logger.info(f"CopilotSdkAdapter: Successfully generated AI explanation for {context.resource_name}")
            return result
        except Exception as e:
            logger.warning(f"CopilotSdkAdapter: AI generation failed ({type(e).__name__}: {e}); falling back to mock explanation")
            return MockCopilotAdapter().explain_mismatch(context)

    async def _run_sdk_prompt(self, prompt: str) -> str:
        if not self._session:
            raise RuntimeError("Session not initialized")

        logger.debug("CopilotSdkAdapter: Sending prompt to Copilot (reused session)...")
        reply = await self._session.send_and_wait({"prompt": prompt})

        content = self._extract_reply_content(reply)
        if not content:
            logger.error("CopilotSdkAdapter: Empty response from Copilot")
            raise RuntimeError("Empty Copilot response")
        logger.debug(f"CopilotSdkAdapter: Received response ({len(content)} chars)")
        return content

    async def cleanup(self) -> None:
        """Cleanup client and session resources."""
        if self._session is not None:
            logger.debug("CopilotSdkAdapter: Destroying session")
            await self._session.destroy()
            self._session = None
        if self._client is not None:
            logger.info("CopilotSdkAdapter: Stopping client")
            await self._client.stop()
            self._client = None
        logger.info("CopilotSdkAdapter: Cleanup complete")

    def _build_prompt(self, context: MismatchContext) -> str:
        return (
            "You are an Azure infrastructure validator assistant. "
            "Provide a concise mismatch explanation in 2-3 sentences. "
            "Keep response plain text and actionable.\n\n"
            f"Resource Name: {context.resource_name}\n"
            f"Resource Type Label: {context.resource_type_label}\n"
            f"Expected Configuration: {context.expected_configuration}\n"
            f"Actual Configuration: {context.actual_configuration}\n"
            f"Detected Reason: {context.mismatch_reason}"
        )

    def _extract_reply_content(self, reply) -> str:
        if reply is None:
            return ""
        if hasattr(reply, "data") and hasattr(reply.data, "content"):
            return (reply.data.content or "").strip()
        if isinstance(reply, dict):
            data = reply.get("data") or {}
            return str(data.get("content") or "").strip()
        return ""

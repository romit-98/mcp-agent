"""INSECURE BASELINE. Do not use outside the phase 4 baseline evaluation.

The same eight tools as the secured servers, written the way many real agents are: one
all-access database account, the user's identity passed as a plain-text tool argument that the
LLM fills in, and permissions left to the system prompt. It exists to be measured against.
"""

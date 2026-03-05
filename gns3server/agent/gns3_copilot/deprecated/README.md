# Deprecated Context Manager

This directory contains the **advanced context management implementation** that has been replaced with a simplified version.

## What's in Here

- **context_manager.py** (~650 lines)
  - Accurate token counting using tiktoken
  - Tool definition token estimation
  - Custom message trimming with AIMessage + ToolMessage pairing
  - Detailed logging and diagnostics

## Why Was It Moved?

The advanced implementation was **over-engineered** for the current use case:

| Feature | Complexity | Necessity | Current Status |
|---------|-----------|-----------|----------------|
| Template injection | Low | ✅ Essential | **Kept** (in new version) |
| Token counting (tiktoken) | High | ❓ Optional | Moved here |
| Message trimming | Medium | ❓ Optional | **Simplified** (LangChain native) |
| Tool token estimation | High | ❓ Optional | Moved here |
| AIMessage/ToolMessage pairing | High | ✅ Important | Moved here |
| 3 strategies (conservative/balanced/aggressive) | Low | ✅ Useful | **Kept** (in new version) |

## When to Use This Implementation

### Use the deprecated version if:

1. **You need accurate token counting**
   - Your model has strict token limits
   - You need to know exact token usage
   - You're working with cost-sensitive applications

2. **You have many tools**
   - Tool definitions consume significant tokens (500-1500 per tool)
   - You need to account for tool tokens in context limit

3. **You need AIMessage + ToolMessage pairing**
   - Your LLM requires tool calls and results to stay together
   - You've encountered errors from orphaned ToolMessages

4. **You need detailed diagnostics**
   - Debugging context limit issues
   - Optimizing token usage
   - Fine-tuning context strategy

### Use the current simplified version if:

1. ✅ You just need topology injection
2. ✅ Your model has large context (128K+ tokens)
3. ✅ Conversations are typically short (<50 turns)
4. ✅ You don't need exact token counts

## How to Restore the Advanced Version

If you find you need the advanced features:

```python
# 1. Remove current simplified version
rm gns3server/agent/gns3_copilot/agent/context_manager.py

# 2. Restore from deprecated
cp gns3server/agent/gns3_copilot/deprecated/context_manager.py \
   gns3server/agent/gns3_copilot/agent/context_manager.py
```

## Key Differences

### Simplified Version (Current)
```python
# ~200 lines
- Uses LangChain's native trim_messages
- Simple token estimation (char count / 4)
- Template injection for topology
- 3 strategies: conservative/balanced/aggressive
```

### Advanced Version (Deprecated)
```python
# ~650 lines
- Custom trimming with AIMessage/ToolMessage pairing
- Accurate tiktoken-based token counting
- Tool definition token estimation
- Detailed logging with token breakdown
- Template injection for topology
- 3 strategies: conservative/balanced/aggressive
```

## Performance Comparison

| Metric | Simplified | Advanced |
|--------|-----------|----------|
| Code size | ~200 lines | ~650 lines |
| Token accuracy | ~80% (estimation) | ~95%+ (tiktoken) |
| Trimming safety | Good | Excellent |
| Execution speed | Fast | Slower (tiktoken overhead) |
| Maintenance | Low | High |

## Future Considerations

If the simplified version proves insufficient:
1. Consider adding tiktoken back (but keep architecture simple)
2. Use LangChain's more advanced trim_messages features
3. Add optional tool token estimation
4. Consider a hybrid approach: simple by default, advanced when needed

---

**Moved**: 2025-03-05
**Reason**: Simplification for current use case
**Status**: Available for future use if needed

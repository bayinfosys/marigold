## Eval Models Integration Summary

**Core Concept:**
Add eval model types alongside generation models to enable quality/safety checks in your workflow orchestration.

**New Model Types to Add:**

1. **text-eval** - Scores text outputs (toxicity, bias, readability)
   - Input: text
   - Output: scores dict
   - Examples: toxic-bert, bias-detection, readability metrics

2. **text-similarity-eval** - Compares text pairs (semantic similarity, BERTScore)
   - Input: text_pair {text1, text2}
   - Output: similarity_score (0.0-1.0)
   - Examples: sentence-transformers models

3. **image-eval** - Scores images (aesthetic quality, NSFW detection)
   - Input: image
   - Output: scores/labels
   - Examples: aesthetic-predictor, nsfw-detector

4. **image-text-eval** - Scores image-text alignment (CLIP scoring)
   - Input: image_text_pair
   - Output: similarity_score
   - Examples: CLIP models

**Workflow Pattern:**
```
Generate → Evaluate → Threshold Check → Retry/Accept
```

Example:
```
1. Queue: instruct (qwen2) → text output
2. Queue: text-eval (toxic-bert) → {toxic: 0.02}
3. Logic: if toxic < 0.1 → accept, else → regenerate
```

**Implementation:**
- Handlers follow same pattern as existing models (load from HF, cache on EFS)
- Evals run independently via SQS queues
- Orchestration layer chains generation + eval steps
- Thresholds/retry logic lives in orchestration, not handlers

**Benefits:**
- Decouple generation from validation
- Reuse eval models across different generators
- Scale eval independently of generation
- Audit trail via queue messages

# Implementation Roadmap

1. Freeze protocol.
2. Build Form 5500 sponsor universe.
3. Create sponsor-to-SEC CIK crosswalk.
4. Validate funded-status outcome.
5. Construct structured X.
6. Implement temporal leakage controls.
7. Fit M0-M2.
8. Build historical 10-K Item 1A corpus.
9. Fit M3 conventional NLP.
10. Implement governed GenAI extraction.
11. Conduct human extraction validation.
12. Construct Z.
13. Construct frozen interaction vector I.
14. Fit M4-M6.
15. Evaluate forecasting performance.
16. Evaluate calibration.
17. Evaluate tail risk.
18. Run ablations.
19. Run uncertainty and robustness analyses.
20. Freeze publication results.

## Frozen Milestone Sequence After v0.5.0

The controlled Milestone-4 release is `v0.5.0-structured-panel`.

The post-structured-panel sequence is frozen as:

- Milestone 5 - Outcome Construction -> `v0.6.0-outcomes`
- Milestone 6 - Temporal Integrity System -> `v0.7.0-temporal-integrity`
- Milestone 7 - Structured Baselines -> `v0.8.0-structured-baselines`
- Milestone 8 - Time-Filtered 10-K Corpus -> `v0.9.0-corpus`
- Milestone 9 - Conventional NLP Comparator -> `v0.10.0-nlp-baseline`

### Milestone 5 Internal Steps

1. Step 5.0 - freeze outcome-construction contract and kickoff.
2. Step 5.1 - construct one-year-ahead continuous outcomes.
3. Step 5.2 - freeze deterioration threshold and binary outcome.
4. Step 5.3 - finalize and freeze outcome artifact.
5. Step 5.4 - merge `develop` and tag `v0.6.0-outcomes`.

The next authorized operation after Step 5.0 is Step 5.1.

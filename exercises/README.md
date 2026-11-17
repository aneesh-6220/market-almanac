# Exercises

Five self-contained exercises from [docs/ENGINEERING_LEARNING_GUIDE.md](../docs/ENGINEERING_LEARNING_GUIDE.md).
Implement the function in each `exN_*.py` (each currently raises `NotImplementedError`), then run:

```bash
uv run pytest exercises/tests -q              # all
uv run pytest exercises/tests/test_ex1_holm.py -q
```

These tests are not part of `make test`. They fail until you implement the stubs.

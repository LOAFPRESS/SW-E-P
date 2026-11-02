# Stage-1 prompt: is this review comment Valid, General, or None?

## Role

You are a senior software engineering researcher who manually annotates code
review comments. You work carefully, you never invent issues that are not in
the text, and you always answer with a single JSON object.

## Task

Given one code review comment and the code changes it was posted on, decide
whether the comment identifies at least one **valid** issue or suggestion, and
extract every distinct issue as an actionable checklist item.

## Label definitions

- `None` - the comment contains no issue and no suggestion. This includes pure
  approvals ("LGTM", "nice"), pure questions that only ask for information, and
  comments describing what the code already does.
- `General` - the comment does contain one or more issues or suggestions, but
  every one of them is too vague to act on without further discussion, e.g.
  "please improve readability", "this could be cleaner", "consider tests".
- `Valid` - at least one issue or suggestion is specific and actionable: it
  points to concrete code, a concrete behaviour, a concrete rule, or a
  concrete missing case, so that a developer could act on it directly.

## Decision procedure

1. Read the comment and the reviewed changes. The changed lines are the only
   code the reviewer could see; do not require the reviewer to know other files.
2. Pure praise, pure thanks and pure questions are `None`.
3. If the comment mixes praise with a request, keep only the request.
4. Split the comment into independent issues. Each issue must be a single
   actionable item, phrased as an instruction with the concrete location or
   symbol it refers to. Merge duplicates. Do not add issues the reviewer did
   not raise.
5. If at least one extracted issue is specific and actionable, the label is
   `Valid` and the checklist contains exactly those actionable issues. If all
   issues are vague, the label is `General` and `issues` is empty. Otherwise the
   label is `None` and `issues` is empty.
6. When the comment is testable only by assuming intent, prefer `General` over
   inventing specificity, and prefer `Valid` when the reviewer named the
   concrete problem.

## Input

### Review comment

```
${comment_text}
```

### Reviewed code changes (unified diff)

```
${review_diff}
```

### Annotation context

- Source of the comment: ${source}
- Review granularity: ${granularity}
- Action type: ${action_name}
- Trigger: ${trigger}
- Repository: ${repo}

## Output

Return **one** JSON object and nothing else, without markdown fences:

```
{"label": "None|General|Valid", "issues": ["..."], "rationale": "..."}
```

- `issues`: array of strings, at most 6 items; empty unless the label is `Valid`.
  Each item states the concrete problem and the concrete fix.
- `rationale`: at most 60 words, referring to the text of the comment.

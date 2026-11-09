Input Format:
Code Review:
- Reviewed Path: The file path of the code change.
- Reviewed Change: The code change under review. ("+" indicates added lines, "-" indicates removed lines)
- Review Comment: A comment for the above changes, which may includes issues or suggestions.

Task: List the issues or suggestions raised in the Review Comment, and determine whether they are valid or not.
The valid issues or suggestions should be:
- Focus on the reviewed file itself.
- Actionable: Require a change to the reviewed file.
- Specific: Includes details to locate which parts of the Reviewed Change should be modified.
(Suggestions that are expressed in a indirect manner are acceptable, including those framed as questions.)
The following are considered only general issues or suggestions, but NOT valid:
- Comments that lack any specific details, and could apply to any code review scenario.
- Comments that only request checking of resources, without requiring specific code modifications.
The following are NOT considered issues or suggestions at all:
- Items that have been implemented in the Reviewed Change, as they are the descriptions of the existing code changes.
- Suggestions that are unrelated to the reviewed file (e.g., requests for more context).
Additional guidance for borderline cases (the rules above still decide; use this only to resolve ambiguity):
- A review that says it found no serious problems and then still lists improvement suggestions ("add comments", "use consistent naming", "add unit tests") does contain general items. Use "Not Contain Any Issues Or Suggestions" only when the comment asks for no change at all, for example pure praise, a summary of the change, or a statement that the code looks fine and nothing else.
- Hedged wording ("could be improved", "consider", "you might want to", "it would be better if") does not by itself make an item general. If the item names a concrete location, function, variable, configuration key, or a concrete kind of change, treat it as valid.
- A walkthrough of what the reviewed change does is a description, not an item; it neither adds nor removes items from the comment.
- A short comment is still a valid item when, read against the Reviewed Change, it asks for a specific modification to the reviewed file.

After completing the analysis, classify the entire review comment into one of the following categories:
- Not Contain Any Issues Or Suggestions: The review comment contains no issues or suggestions.
- Only Contain General Issues Or Suggestions: The review comment only contains general issues or suggestions.
- Contain Valid Issues Or Suggestions: The review comment contains at least one valid issues or suggestions.

Output Format:
Issues or Suggestions: List valid items from the Review Comment clearly, preserving code details, including inline code blocks and multi-line code snippets, and using the original wording as much as possible.
Classification: Based on the listed items, select one of "Not Contain Any Issues Or Suggestions", "Only Contain General Issues Or Suggestions" or "Contain Valid Issues Or Suggestions" as the final classification without more explanations.

Input:
Code Review:
- Reviewed Path: $reviewed_path
- Reviewed Change: $reviewed_change
- Review Comment: $review_comment

Output: List the identified issues or suggestions, and make the final classification.

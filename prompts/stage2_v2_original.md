Input Format:
Code Review:
- Reviewed Path: The file path of the code change.
- Reviewed Change: The code change under review. ("+" indicates added lines, "-" indicates removed lines)
- Review Comment: A list of issues or suggestions for the above changes.
Subsequent Code Changes: A cumulative code changes made to the reviewed file after the review.

Task: For each item in the Review Comment, analyze whether it has been addressed by the Subsequent Code Changes by determining if:
- The issue has been completely resolved.
- The suggestion has been completely followed. (If the suggestion includes concrete code examples, it does not need to be followed exactly. As long as the code change serves the same intended purpose, the suggestion can be considered addressed.)
After completing the analysis, classify the entire review comment into one of the following categories:
- Not Addressed: None of the issues or suggestions have been addressed by the Subsequent Code Changes.
- Partly Addressed: Some but not all issues or suggestions have been addressed.
- Fully Addressed: All issues or suggestions have been addressed.
If the code relevant to the Review Comment has been completely removed in the Subsequent Code Changes, and it is not possible to determine whether the removal was an intentional response to the comment, you can classify it as "Not Enough Information".

Output Format:
Analysis details:
- Addressed Items: List the issues or suggestions that have been addressed.
- Unaddressed Items: List the issues or suggestions that have not been addressed.
Classification: Based on the Addressed Items and Unaddressed Items, select one of "Not Addressed", "Partly Addressed", "Fully Addressed", or "Not Enough Information" as the final classification without more explanations.

Input:
Code Review:
- Reviewed Path: $reviewed_path
- Reviewed Change: $reviewed_change
- Review Comment: $review_comment_items

$subsequent_changes_block

Output: List the addressed and unaddressed items, and make the final classification.

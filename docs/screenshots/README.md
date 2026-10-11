# Screenshots

Captured on 2026-10-10 from the application running locally, with Playwright driving Microsoft Edge:

- **Desktop:** 1440 px wide, light theme. Taller windows were used where an answer is long.
- **Phone:** 390 × 844.

Setup when captured:

- **Knowledge base:** the 17 crawled `help.synchronik.co.in` pages plus the curated FAQ (18 documents).
- **Database:** local SQLite; a separate copy with no prior conversations, so the sidebar shows only these chats.
- **Model:** Gemini enabled (`gemini-3.5-flash-lite` for answers, `gemini-3.8-flash` for images); the answers shown
  are the real generated answers.
- **Demo inputs:** the exam circular (DOCX) and the "attendance locked" error image are fictional files made for these
  screenshots. No real student or staff data appears.
- **Admin key:** not entered, so the Knowledge Base page shows the public view.

| File | Shows |
|---|---|
| `homepage.png` | Home screen with suggested questions |
| `documentation-answer.png` | Answer to "How does attendance work?" with its help-portal sources |
| `document-attachment.png` | An attached DOCX circular, its summary and a follow-up question |
| `image-question.png` | An uploaded error screenshot explained with the matching help-portal page |
| `knowledge-base.png` | Knowledge Base page listing the indexed documents |
| `mobile.png` | The attachment conversation at phone width |

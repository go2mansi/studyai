# StudyAI API

All endpoints are under `/api`, return JSON (except downloads) and use cookie sessions. Errors look like
`{"error": "Human-readable message"}`. Common codes: 400 validation, 401 not logged in, 404 not found
(also used for other users' records), 409 conflict, 413 file too large, 415 unsupported type, 502 AI service problem.
The browser sends `X-TZ-Offset` (minutes) so streaks/daily minutes use the user's local day.
Every endpoint except `/api/health` and `/api/auth/*` needs login.

| Method | Path | Purpose | Request | Response / notes |
|---|---|---|---|---|
| GET | /api/health | Liveness + DB check | - | `{status, database, db_ok, ai_configured, max_upload_mb, persistent_storage}`; 503 if DB down |
| POST | /api/auth/signup | Create account + log in | `{name,email,password>=8}` | 201 `{user}`; 400 invalid, 409 email taken |
| POST | /api/auth/login | Log in | `{email,password}` | `{user}`; 401 invalid |
| POST | /api/auth/logout | Log out | - | `{ok}` |
| GET | /api/me | Current user + profile | - | `{user, profile}` |
| PUT/POST | /api/profile | Save learning profile | `{course,preferred_language,explanation_style(Detailed\|Simple\|Exam-focused),daily_minutes(10-600),exam_date}` | `{profile}` |
| GET | /api/documents | List documents | - | `{documents:[{id,title,created_at,chunks}]}` |
| POST | /api/upload | Upload + index PDF/TXT/MD | multipart `file` | 201 `{document_id,title,chunks}`; 415/413/400 |
| DELETE | /api/documents/{id} | Delete document (cascades) | - | `{ok}`; 404 |
| GET | /api/search?q= | Search documents, notes, flashcards | q>=2 chars | `{results:[{type,id,title,snippet}]}` |
| POST | /api/chat | Ask the tutor | `{document_id,question<=2000,mode(normal\|simple\|detailed\|exam\|compare)}` | `{answer,sources}`; 502 AI error |
| GET | /api/chat/history?document_id= | Saved conversation | - | `{messages}` |
| DELETE | /api/chat?document_id= | Clear conversation | - | `{ok}` |
| POST | /api/notes | Generate + save notes | `{document_id,request?,title?}` | 201 `{id,title,content}` |
| GET | /api/notes, /api/notes/{id} | List / read notes | - | `{notes}` / note |
| DELETE | /api/notes/{id} | Delete note | - | `{ok}` |
| GET | /api/notes/{id}/download?format=pdf\|docx | Export note | - | file |
| POST | /api/flashcards | Generate + save a deck | `{document_id,count 5-20}` | 201 `{deck_id,cards}` |
| GET | /api/flashcards, /api/flashcards/{id} | List decks / read deck | - | `{decks}` / `{cards}` |
| DELETE | /api/flashcards/{id} | Delete deck | - | `{ok}` |
| POST | /api/quiz/generate | Generate a 4-option quiz | `{document_id,count 5-20,difficulty}` | 201 `{quiz_id}` (invalid AI questions are dropped) |
| GET | /api/quizzes | Quiz history | - | `{quizzes:[{id,document_title,total,answered,correct,percentage}]}` |
| GET | /api/quiz/{id} | Questions (answers hidden until answered) | - | `{questions}` |
| POST | /api/quiz/{id}/answer | Answer one question once | `{question_id,answer 0-3}` | `{correct,correct_index,explanation}`; 409 already answered |
| GET | /api/quiz/{id}/result | Score + review | - | `{total,answered,correct,percentage,details}` |
| DELETE | /api/quiz/{id} | Delete quiz | - | `{ok}` |
| POST | /api/planner | Generate + save study plan | `{document_id,days 1-30,start_date,minutes}` | 201 `{plan_id,plan}`; 400 past date |
| GET | /api/plans | List plans | - | `{plans}` |
| POST | /api/plans/{id}/tasks | Tick / untick a task | `{day,index,done}` | `{plan}` |
| GET | /api/plans/{id}/download | Plan as PDF | - | file |
| DELETE | /api/plans/{id} | Delete plan | - | `{ok}` |
| GET | /api/dashboard | Stats, 14-day chart, badges, recent activity | - | see app |
| GET | /api/topics | Topic accuracy from quizzes | - | `{topics}` |
| GET | /api/coach | AI recommendation from the above | - | `{answer}` |
| GET | /api/ai-status | Diagnose NVIDIA key (never returns the key) | - | `{configured,models_http,message}` |

Interactive docs: this project uses Flask, so there is no auto-generated Swagger UI; this table is the reference.

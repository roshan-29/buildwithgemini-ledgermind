# My agent: LedgerMind (Personal Finance & Expense Tracker Concierge)
One-liner: A conversational financial agent that helps individuals effortlessly log expenses and track budgets with a catalog of categorized transactions, monthly budgets, and spending analytics.

Tool coverage:
- Memory: User financial preferences, monthly budget limits per category (e.g. Dining, Groceries, Utilities), recurring subscriptions, and ongoing savings goals.
- Tools: 
  - `log_expense(amount, merchant, category, date, payment_method)`: Add an extracted or manual transaction.
  - `list_expenses(start_date, end_date, category)`: Query transaction history.
  - `get_budget_status(month)`: Compare actual expenditures vs set budget limits.
  - `analyze_subscriptions()`: Identify active and potential ghost recurring subscriptions.
- Catalog/UI: Monthly transaction ledger and category budget summary rendered as A2UI rich cards and tables.
- Image gen: Infographic/badge visualization of monthly savings milestones or spending alert cards.
- Sandbox: Python code sandbox for dynamic financial math (run rate calculations, spending projections, month-over-month percentage delta analysis).

Recommended for every project: memory, storage (Firestore for transactions), tools, image generation, A2UI
Agent-specific / stretch (pick what fits): Gemini Vision OCR for receipt parsing, code sandbox for financial projections and budget math, FastAPI proxy + Next.js / React frontend with Tailwind CSS.

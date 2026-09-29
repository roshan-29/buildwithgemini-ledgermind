import datetime
from google.cloud import firestore

GCP_PROJECT_ID = "qwiklabs-gcp-04-971e8638e31a"

def seed_database():
    db = firestore.Client(project=GCP_PROJECT_ID)
    expenses_ref = db.collection("expenses")

    sample_expenses = [
        {
            "amount": 78.45,
            "merchant": "Trader Joe's",
            "category": "Groceries",
            "date": "2026-09-25",
            "payment_method": "Credit Card",
            "description": "Weekly grocery run with fresh produce",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "amount": 42.50,
            "merchant": "Blue Bottle Coffee",
            "category": "Dining",
            "date": "2026-09-26",
            "payment_method": "Apple Pay",
            "description": "Coffee and pastries with team",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "amount": 14.99,
            "merchant": "Netflix",
            "category": "Entertainment",
            "date": "2026-09-27",
            "payment_method": "Debit Card",
            "description": "Monthly standard streaming subscription",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "amount": 120.00,
            "merchant": "Pacific Gas & Electric",
            "category": "Utilities",
            "date": "2026-09-28",
            "payment_method": "Bank Transfer",
            "description": "Monthly electric & gas utility bill",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "amount": 34.20,
            "merchant": "Uber",
            "category": "Transportation",
            "date": "2026-09-28",
            "payment_method": "Credit Card",
            "description": "Ride home from downtown conference",
            "created_at": firestore.SERVER_TIMESTAMP
        }
    ]

    for item in sample_expenses:
        doc_ref = expenses_ref.document()
        doc_ref.set(item)
        print(f"Added expense: {item['merchant']} (${item['amount']}) with ID: {doc_ref.id}")

    print("Seeding completed successfully!")

if __name__ == "__main__":
    seed_database()

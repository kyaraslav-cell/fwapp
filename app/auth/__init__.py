"""Accounts and sign-in.

Split so that everything decidable without a database stays pure and testable:

    passwords.py   hashing and verification (stdlib scrypt, no dependency)
    validation.py  what makes an email or a password acceptable, as i18n keys
    tokens.py      session token minting and the hash that is what we store
    google.py      the Google OAuth exchange, and what happens when it is off
    service.py     the only module that touches the database

`docs/adr/0004-accounts-and-sign-in.md` records why each of those choices was
made, including the ones that look like omissions.
"""

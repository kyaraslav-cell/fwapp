"""Background work: a queue in the database, drained by the scheduler.

    queue.py     enqueue, claim, finish - the state machine, no domain logic
    handlers.py  what each kind of job actually does
    runner.py    the scheduler tick that drains one job at a time

Split so the state machine can be tested without touching a network or a
handler, and a handler can be tested without a scheduler.
"""

"""FORMA production engine (Project #3 on): one declarative project spec + generic stills, clips and budget.

    spec.py     project.json -> ProjectSpec (checkpoints, shots, derived stills and clips)
    rules.py    doctrine checks on a spec: clip counts, construction order, material flow, camera rules
    state.py    still and clip state machines, derived only from persisted files + the manifest
    stills.py   manual ChatGPT stills: upload (local only), hash, approve, replace -> changed
    budget.py   per-clip spend approval, caps, one approval = one submission
    submit.py   the only paid step: one clip -> one fal job, recorded before anything else

Earlier projects (Cliffside, Alpine, the train car) keep their own scripts as history.
"""

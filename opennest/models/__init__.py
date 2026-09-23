"""What AI this Mac can run, and which models exist to choose from.

Phase 11B. Five modules, each answering a different question:

============================  ====================================================
:mod:`~opennest.models.machine`        what is this Mac?
:mod:`~opennest.models.catalog`        which models does Open Nest know about?
:mod:`~opennest.models.remote`         has that list changed since this release?
:mod:`~opennest.models.discovery`      which are already here, and what does a
                                       provider say it has today?
:mod:`~opennest.models.compatibility`  given all of that, what should this Mac run?
============================  ====================================================

The separation is the point. A hard-coded list goes stale, a live provider query is
unavailable offline and unstable when it is not, and a public model search recommends
whatever a stranger uploaded this morning. None of the three is the answer on its own,
so Open Nest keeps the compatibility decision and lets the others supply availability.
"""

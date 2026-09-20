"""Open Nest bootstrap layer.

Everything in this package runs *before* the Open Nest environment exists, using
whatever Python the parent's Mac happens to have. macOS still ships Python 3.9, so this
package must stay Python 3.9-compatible and must not import the ``opennest`` runtime.

See PLAN.md section 2.1.
"""

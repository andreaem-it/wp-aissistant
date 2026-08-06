"""FastAPI routers, one module per area of the API.

`main.py` grew to 8000 lines and 182 endpoints across nine areas, which made every new block
slower and riskier than the last. Areas move out one at a time, each move verified by the full
test suite and changing no path, method or response.
"""

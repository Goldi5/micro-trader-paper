import db as db14

m14 = db14.MTDB()
tid14 = 50
c14 = m14.live_request_create(tid14, requested_by=2, broker_connection_id=1, note="Test")
rid14 = c14["id"]
m14.live_request_review(rid14, tid14, reviewed_by=3)
m14.live_request_approve(rid14, tid14, approved_by=3, note="OK")
m14.live_request_activate(rid14, tid14)
m14.live_request_create(tid14, requested_by=2)
m14.live_request_review(rid14, 999, reviewed_by=3)
c314 = m14.live_request_create(51, requested_by=2)
print("reject-create:", c314.get("ok"), c314.get("id"))
if c314["ok"]:
    m14.live_request_review(c314["id"], 51, reviewed_by=3)
    rj14 = m14.live_request_reject(c314["id"], 51, rejected_by=3, note="Nein")
    print("reject:", rj14.get("ok"), rj14.get("status"), rj14.get("error", ""))
m14.close()

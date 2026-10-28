"""Contabilidad y tesorería de La Santaniana."""
import csv, io, os, uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, current_app, jsonify, render_template, request, session, send_from_directory, Response
from werkzeug.utils import secure_filename
from db_compat import get_connection
bp_contabilidad=Blueprint("contabilidad",__name__)
ROLES={"admin","contabilidad"}
def allowed(): return session.get("rol") in ROLES
def denied(): return jsonify({"ok":False,"error":"Acceso reservado a Contabilidad y Administración."}),403
def audit(c,accion,entidad,rid,detalle=""):
 c.execute("INSERT INTO contabilidad_auditoria(usuario,rol,accion,entidad,entidad_id,detalle,fecha) VALUES(?,?,?,?,?,?,?)",(session.get("nombre") or session.get("usuario") or "?",session.get("rol",""),accion,entidad,rid,detalle[:400],datetime.now().isoformat(timespec="seconds")))
def init_contabilidad(app):
 folder=os.path.join(app.root_path,"uploads","contabilidad");os.makedirs(folder,exist_ok=True);app.config["CONTABILIDAD_UPLOAD_DIR"]=folder
 c=get_connection()
 try:
  c.execute("""CREATE TABLE IF NOT EXISTS contabilidad_facturas(id INTEGER PRIMARY KEY AUTOINCREMENT,numero TEXT NOT NULL,proveedor TEXT NOT NULL,ruc TEXT DEFAULT '',concepto TEXT NOT NULL,categoria TEXT DEFAULT 'General',fecha_emision TEXT NOT NULL,fecha_vencimiento TEXT DEFAULT '',importe INTEGER NOT NULL,saldo INTEGER NOT NULL,estado TEXT DEFAULT 'pendiente',archivo TEXT DEFAULT '',archivo_nombre TEXT DEFAULT '',creado_por TEXT,creado_en TEXT,autorizado_por TEXT DEFAULT '',autorizado_en TEXT DEFAULT '')""")
  c.execute("""CREATE TABLE IF NOT EXISTS contabilidad_pagos(id INTEGER PRIMARY KEY AUTOINCREMENT,factura_id INTEGER,beneficiario TEXT NOT NULL,concepto TEXT NOT NULL,fecha TEXT NOT NULL,importe INTEGER NOT NULL,metodo TEXT NOT NULL,cuenta TEXT DEFAULT '',referencia TEXT DEFAULT '',estado TEXT DEFAULT 'pendiente',solicitado_por TEXT,autorizado_por TEXT DEFAULT '',autorizado_en TEXT DEFAULT '',realizado_por TEXT DEFAULT '',realizado_en TEXT DEFAULT '',comprobante TEXT DEFAULT '',comprobante_nombre TEXT DEFAULT '',creado_en TEXT)""")
  c.execute("""CREATE TABLE IF NOT EXISTS contabilidad_movimientos(id INTEGER PRIMARY KEY AUTOINCREMENT,fecha TEXT NOT NULL,tipo TEXT NOT NULL,cuenta TEXT NOT NULL,metodo TEXT NOT NULL,concepto TEXT NOT NULL,referencia TEXT DEFAULT '',importe INTEGER NOT NULL,pago_id INTEGER,usuario TEXT,creado_en TEXT)""")
  c.execute("""CREATE TABLE IF NOT EXISTS contabilidad_auditoria(id INTEGER PRIMARY KEY AUTOINCREMENT,usuario TEXT,rol TEXT,accion TEXT,entidad TEXT,entidad_id INTEGER,detalle TEXT,fecha TEXT)""")
  c.commit()
 finally:c.close()
def rows(sql,args=()):
 c=get_connection()
 try:return [dict(r) for r in c.execute(sql,args).fetchall()]
 finally:c.close()
def amount(v):
 try:
  n=Decimal(str(v))
  if not n.is_finite() or n<=0 or n!=n.to_integral_value():raise ValueError()
  return int(n)
 except (InvalidOperation,ValueError,TypeError):raise ValueError("El importe debe ser un número entero de guaraníes mayor a cero.")
def save_file(field):
 f=request.files.get(field)
 if not f or not f.filename:return ("","")
 name=secure_filename(f.filename);ext=name.rsplit(".",1)[-1].lower() if "." in name else ""
 if ext not in {"pdf","png","jpg","jpeg","webp"}:raise ValueError("Adjuntá PDF o imagen (PDF, PNG, JPG o WEBP).")
 stored=uuid.uuid4().hex+"."+ext;f.save(os.path.join(current_app.config["CONTABILIDAD_UPLOAD_DIR"],stored));return stored,name[:200]
@bp_contabilidad.route("/contabilidad")
def page():
 if not allowed():return ("Sin permiso",403)
 return render_template("contabilidad.html",usuario=session.get("nombre") or session.get("usuario"),es_admin=session.get("rol")=="admin")
@bp_contabilidad.route("/api/contabilidad/resumen")
def summary():
 if not allowed():return denied()
 f=rows("SELECT COUNT(*) total,COALESCE(SUM(saldo),0) saldo FROM contabilidad_facturas WHERE estado!='anulada'")[0]
 p=rows("SELECT COUNT(*) total,COALESCE(SUM(importe),0) monto FROM contabilidad_pagos WHERE estado='pendiente'")[0]
 m=rows("SELECT cuenta,COALESCE(SUM(CASE WHEN tipo='ingreso' THEN importe ELSE -importe END),0) saldo FROM contabilidad_movimientos GROUP BY cuenta")
 return jsonify({"facturas":f,"pagos":p,"cuentas":m})
@bp_contabilidad.route("/api/contabilidad/facturas",methods=["GET","POST"])
def invoices():
 if not allowed():return denied()
 if request.method=="GET":
  q=(request.args.get("q") or "").strip()
  return jsonify(rows("SELECT * FROM contabilidad_facturas WHERE (?='' OR proveedor LIKE ? OR numero LIKE ? OR concepto LIKE ?) ORDER BY id DESC LIMIT 500",(q,"%"+q+"%","%"+q+"%","%"+q+"%")))
 d=request.form
 if any(not (d.get(k) or "").strip() for k in ("numero","proveedor","concepto","fecha_emision","importe")):return jsonify({"error":"Completá número, proveedor, concepto, fecha e importe."}),400
 try:a=amount(d["importe"]);file,original=save_file("archivo")
 except ValueError as e:return jsonify({"error":str(e)}),400
 c=get_connection()
 try:
  if c.execute("SELECT id FROM contabilidad_facturas WHERE numero=? AND proveedor=? AND estado!='anulada'",(d["numero"].strip(),d["proveedor"].strip())).fetchone():return jsonify({"error":"Ya existe esa factura para el proveedor."}),409
  cur=c.execute("INSERT INTO contabilidad_facturas(numero,proveedor,ruc,concepto,categoria,fecha_emision,fecha_vencimiento,importe,saldo,estado,archivo,archivo_nombre,creado_por,creado_en) VALUES(?,?,?,?,?,?,?,?,?,'pendiente',?,?,?,?)",(d["numero"].strip(),d["proveedor"].strip(),d.get("ruc",""),d["concepto"].strip(),d.get("categoria","General"),d["fecha_emision"],d.get("fecha_vencimiento",""),a,a,file,original,session.get("nombre") or session.get("usuario"),datetime.now().isoformat(timespec="seconds")))
  audit(c,"registrar factura","factura",cur.lastrowid,d["numero"]);c.commit();return jsonify({"ok":True,"id":cur.lastrowid})
 finally:c.close()
@bp_contabilidad.route("/api/contabilidad/facturas/<int:i>/autorizar",methods=["POST"])
def approve_invoice(i):
 if session.get("rol")!="admin":return denied()
 c=get_connection()
 try:
  cur=c.execute("UPDATE contabilidad_facturas SET estado='autorizada',autorizado_por=?,autorizado_en=? WHERE id=? AND estado='pendiente'",(session.get("nombre") or session.get("usuario"),datetime.now().isoformat(timespec="seconds"),i))
  if not c.execute("SELECT id FROM contabilidad_facturas WHERE id=? AND estado='autorizada'",(i,)).fetchone():return jsonify({"error":"Factura inexistente o ya procesada."}),409
  audit(c,"autorizar factura","factura",i);c.commit();return jsonify({"ok":True})
 finally:c.close()
@bp_contabilidad.route("/api/contabilidad/pagos",methods=["GET","POST"])
def payments():
 if not allowed():return denied()
 if request.method=="GET":return jsonify(rows("SELECT p.*,f.numero factura_numero FROM contabilidad_pagos p LEFT JOIN contabilidad_facturas f ON f.id=p.factura_id ORDER BY p.id DESC LIMIT 500"))
 d=request.json or {}
 try:a=amount(d.get("importe"))
 except ValueError as e:return jsonify({"error":str(e)}),400
 who=(d.get("beneficiario") or "").strip();concept=(d.get("concepto") or "").strip();method=d.get("metodo")
 if not who or not concept or method not in {"Efectivo","Transferencia","Cheque","Débito","Otro"}:return jsonify({"error":"Completá beneficiario, concepto y método."}),400
 fid=d.get("factura_id") or None;c=get_connection()
 try:
  if fid:
   f=c.execute("SELECT * FROM contabilidad_facturas WHERE id=? AND estado='autorizada'",(fid,)).fetchone()
   if not f or f["proveedor"]!=who or a>int(f["saldo"]):return jsonify({"error":"La factura debe estar autorizada, el beneficiario debe coincidir y el importe no superar el saldo."}),400
  cur=c.execute("INSERT INTO contabilidad_pagos(factura_id,beneficiario,concepto,fecha,importe,metodo,cuenta,referencia,estado,solicitado_por,creado_en) VALUES(?,?,?,?,?,?,?,?, 'pendiente',?,?)",(fid,who,concept,d.get("fecha") or date.today().isoformat(),a,method,(d.get("cuenta") or "")[:120],(d.get("referencia") or "")[:180],session.get("nombre") or session.get("usuario"),datetime.now().isoformat(timespec="seconds")))
  audit(c,"crear orden de pago","pago",cur.lastrowid,who);c.commit();return jsonify({"ok":True,"id":cur.lastrowid})
 finally:c.close()
@bp_contabilidad.route("/api/contabilidad/pagos/<int:i>/autorizar",methods=["POST"])
def approve_payment(i):
 if session.get("rol")!="admin":return denied()
 c=get_connection()
 try:
  cur=c.execute("UPDATE contabilidad_pagos SET estado='autorizado',autorizado_por=?,autorizado_en=? WHERE id=? AND estado='pendiente'",(session.get("nombre") or session.get("usuario"),datetime.now().isoformat(timespec="seconds"),i))
  if not c.execute("SELECT id FROM contabilidad_pagos WHERE id=? AND estado='autorizado'",(i,)).fetchone():return jsonify({"error":"Orden inexistente o ya procesada."}),409
  audit(c,"autorizar orden","pago",i);c.commit();return jsonify({"ok":True})
 finally:c.close()
@bp_contabilidad.route("/api/contabilidad/pagos/<int:i>/pagar",methods=["POST"])
def pay(i):
 if not allowed():return denied()
 try:file,original=save_file("comprobante")
 except ValueError as e:return jsonify({"error":str(e)}),400
 c=get_connection()
 try:
  p=c.execute("SELECT * FROM contabilidad_pagos WHERE id=? AND estado='autorizado'",(i,)).fetchone()
  if not p:return jsonify({"error":"Solo se puede registrar una orden autorizada."}),409
  if p["factura_id"]:
   factura=c.execute("SELECT saldo,estado FROM contabilidad_facturas WHERE id=?",(p["factura_id"],)).fetchone()
   if not factura or factura["estado"] not in ("autorizada","pagada") or int(factura["saldo"])<int(p["importe"]):
    return jsonify({"error":"El saldo actual de la factura ya no alcanza para este pago. Revisá las órdenes vinculadas."}),409
  cuenta=(request.form.get("cuenta") or p["cuenta"] or "Caja general").strip()
  saldo=c.execute("SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN importe ELSE -importe END),0) s FROM contabilidad_movimientos WHERE cuenta=?",(cuenta,)).fetchone()["s"]
  if int(saldo)<int(p["importe"]):return jsonify({"error":"Saldo insuficiente en la cuenta. Registrá primero el saldo inicial."}),400
  now=datetime.now().isoformat(timespec="seconds")
  c.execute("UPDATE contabilidad_pagos SET estado='pagado',realizado_por=?,realizado_en=?,comprobante=?,comprobante_nombre=? WHERE id=?",(session.get("nombre") or session.get("usuario"),now,file,original,i))
  if p["factura_id"]:c.execute("UPDATE contabilidad_facturas SET saldo=saldo-?,estado=CASE WHEN saldo-?=0 THEN 'pagada' ELSE 'autorizada' END WHERE id=?",(p["importe"],p["importe"],p["factura_id"]))
  c.execute("INSERT INTO contabilidad_movimientos(fecha,tipo,cuenta,metodo,concepto,referencia,importe,pago_id,usuario,creado_en) VALUES(?,'egreso',?,?,?,?,?,?,?,?)",(date.today().isoformat(),cuenta,p["metodo"],p["concepto"],p["referencia"],p["importe"],i,session.get("nombre") or session.get("usuario"),now))
  audit(c,"registrar pago","pago",i);c.commit();return jsonify({"ok":True})
 finally:c.close()
@bp_contabilidad.route("/api/contabilidad/movimientos",methods=["GET","POST"])
def movements():
 if not allowed():return denied()
 if request.method=="GET":return jsonify(rows("SELECT * FROM contabilidad_movimientos ORDER BY id DESC LIMIT 500"))
 d=request.json or {};typ=d.get("tipo");account=(d.get("cuenta") or "").strip();concept=(d.get("concepto") or "").strip()
 if typ not in {"ingreso","egreso"} or not account or not concept:return jsonify({"error":"Completá tipo, cuenta y concepto."}),400
 try:a=amount(d.get("importe"))
 except ValueError as e:return jsonify({"error":str(e)}),400
 c=get_connection()
 try:
  if typ=="egreso":
   balance=c.execute("SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN importe ELSE -importe END),0) s FROM contabilidad_movimientos WHERE cuenta=?",(account,)).fetchone()["s"]
   if int(balance)<a:return jsonify({"error":"Saldo insuficiente en esa caja o cuenta bancaria."}),400
  cur=c.execute("INSERT INTO contabilidad_movimientos(fecha,tipo,cuenta,metodo,concepto,referencia,importe,usuario,creado_en) VALUES(?,?,?,?,?,?,?,?,?)",(d.get("fecha") or date.today().isoformat(),typ,account,d.get("metodo","Transferencia"),concept,d.get("referencia",""),a,session.get("nombre") or session.get("usuario"),datetime.now().isoformat(timespec="seconds")))
  audit(c,"registrar movimiento","movimiento",cur.lastrowid,concept);c.commit();return jsonify({"ok":True})
 finally:c.close()
@bp_contabilidad.route("/api/contabilidad/adjuntos/<path:name>")
def attachment(name):
 if not allowed():return denied()
 return send_from_directory(current_app.config["CONTABILIDAD_UPLOAD_DIR"],os.path.basename(name))
@bp_contabilidad.route("/api/contabilidad/reportes.csv")
def report():
 if not allowed():return denied()
 data=rows("SELECT id,fecha,beneficiario,concepto,importe,metodo,cuenta,estado,solicitado_por,autorizado_por,realizado_por FROM contabilidad_pagos ORDER BY id DESC")
 s=io.StringIO();s.write("\ufeff");w=csv.writer(s,delimiter=";");w.writerow(["ID","Fecha","Beneficiario","Concepto","Importe Gs.","Método","Cuenta","Estado","Solicitado por","Autorizado por","Pagado por"])
 for r in data:w.writerow([r.get(k,"") for k in ("id","fecha","beneficiario","concepto","importe","metodo","cuenta","estado","solicitado_por","autorizado_por","realizado_por")])
 return Response(s.getvalue(),mimetype="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=contabilidad_pagos.csv"})
@bp_contabilidad.route("/api/contabilidad/movimientos.csv")
def export_movimientos():
 if not allowed():return denied()
 data=rows("SELECT fecha,tipo,cuenta,metodo,concepto,referencia,importe,usuario FROM contabilidad_movimientos ORDER BY fecha DESC,id DESC")
 s=io.StringIO();s.write("\\ufeff");w=csv.writer(s,delimiter=";");w.writerow(["Fecha","Tipo","Caja / banco","Método","Concepto","Referencia","Importe Gs.","Usuario"])
 for r in data:w.writerow([r.get(k,"") for k in ("fecha","tipo","cuenta","metodo","concepto","referencia","importe","usuario")])
 return Response(s.getvalue(),mimetype="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=contabilidad_movimientos.csv"})
@bp_contabilidad.route("/api/contabilidad/facturas.csv")
def export_facturas():
 if not allowed():return denied()
 data=rows("SELECT numero,proveedor,ruc,concepto,categoria,fecha_emision,fecha_vencimiento,importe,saldo,estado,creado_por,autorizado_por FROM contabilidad_facturas ORDER BY id DESC")
 s=io.StringIO();s.write("\\ufeff");w=csv.writer(s,delimiter=";");w.writerow(["N.º factura","Proveedor","RUC","Concepto","Categoría","Emisión","Vencimiento","Importe Gs.","Saldo Gs.","Estado","Registrada por","Autorizada por"])
 for r in data:w.writerow([r.get(k,"") for k in ("numero","proveedor","ruc","concepto","categoria","fecha_emision","fecha_vencimiento","importe","saldo","estado","creado_por","autorizado_por")])
 return Response(s.getvalue(),mimetype="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=contabilidad_facturas.csv"})
@bp_contabilidad.route("/api/contabilidad/auditoria")
def audit_list():
 if not allowed():return denied()
 return jsonify(rows("SELECT * FROM contabilidad_auditoria ORDER BY id DESC LIMIT 300"))

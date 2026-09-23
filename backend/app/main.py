import os, math, random
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sklearn.ensemble import RandomForestRegressor
from ortools.linear_solver import pywraplp

DATABASE_URL=os.getenv("DATABASE_URL","postgresql+psycopg2://ecoloop:ecoloop@db:5432/ecoloop")
engine=create_engine(DATABASE_URL,pool_pre_ping=True)
SessionLocal=sessionmaker(bind=engine,autoflush=False,autocommit=False)
Base=declarative_base()

class Factory(Base):
    __tablename__="factories"
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    industry=Column(String(100),nullable=False)
    location=Column(String(160),nullable=False)
    lat=Column(Float,nullable=False)
    lon=Column(Float,nullable=False)
    email=Column(String(160),default="")
    status=Column(String(30),default="PENDING")
    created=Column(DateTime,default=datetime.utcnow)

class Resource(Base):
    __tablename__="resources"
    id=Column(Integer,primary_key=True)
    factory_id=Column(Integer,ForeignKey("factories.id"),nullable=False)
    direction=Column(String(20),nullable=False)
    resource_type=Column(String(80),nullable=False)
    quantity=Column(Float,nullable=False)
    unit=Column(String(20),default="kWh")
    temperature=Column(Float,default=0)
    quality=Column(String(80),default="standard")
    start=Column(String(5),default="14:00")
    end=Column(String(5),default="17:00")
    reliability=Column(Float,default=.85)
    created=Column(DateTime,default=datetime.utcnow)

class ResourceHistory(Base):
    __tablename__="resource_history"
    id=Column(Integer,primary_key=True)
    resource_id=Column(Integer,ForeignKey("resources.id"),nullable=False)
    day=Column(Date,nullable=False)
    quantity=Column(Float,nullable=False)

class Match(Base):
    __tablename__="matches"
    id=Column(Integer,primary_key=True)
    supplier=Column(Integer,nullable=False)
    consumer=Column(Integer,nullable=False)
    resource=Column(String(80),nullable=False)
    unit=Column(String(20),default="kWh")
    quantity=Column(Float,nullable=False)
    distance=Column(Float,nullable=False)
    score=Column(Float,nullable=False)
    co2=Column(Float,nullable=False)
    savings=Column(Float,nullable=False)
    reasons=Column(Text,default="")
    run_id=Column(String(40),default="")
    created=Column(DateTime,default=datetime.utcnow)

class Run(Base):
    __tablename__="runs"
    id=Column(Integer,primary_key=True)
    run_id=Column(String(40),unique=True)
    created=Column(DateTime,default=datetime.utcnow)
    matches=Column(Integer,default=0)
    reused=Column(Float,default=0)
    co2=Column(Float,default=0)
    savings=Column(Float,default=0)

Base.metadata.create_all(engine)

class LoginIn(BaseModel): username:str; password:str
class FactoryIn(BaseModel): name:str; industry:str; location:str; lat:float; lon:float; email:str=""
class ResourceIn(BaseModel):
    factory_id:int; direction:str; resource_type:str; quantity:float=Field(gt=0); unit:str="kWh"
    temperature:float=0; quality:str="standard"; start:str="14:00"; end:str="17:00"; reliability:float=Field(.85,ge=0,le=1)
class WhatIf(BaseModel): factory_id:int; reduction:float=Field(40,ge=0,le=100)

app=FastAPI(title="EcoLoop API",version="3.1.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

def wait_db():
    import time
    for _ in range(30):
        try: Base.metadata.create_all(engine); return
        except Exception: time.sleep(2)
wait_db()

def dto_factory(f): return {"id":f.id,"name":f.name,"industry":f.industry,"location":f.location,"lat":f.lat,"lon":f.lon,"email":f.email,"status":f.status,"created":f.created.isoformat() if f.created else None}
def dto_resource(r,s):
    f=s.get(Factory,r.factory_id)
    return {"id":r.id,"factory_id":r.factory_id,"factory_name":f.name if f else "Unknown","direction":r.direction,"resource_type":r.resource_type,"quantity":r.quantity,"unit":r.unit,"temperature":r.temperature,"quality":r.quality,"start":r.start,"end":r.end,"reliability":r.reliability,"created":r.created.isoformat() if r.created else None}
def dist(a,b):
    R=6371; dlat=math.radians(b.lat-a.lat); dlon=math.radians(b.lon-a.lon)
    x=math.sin(dlat/2)**2+math.cos(math.radians(a.lat))*math.cos(math.radians(b.lat))*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(max(0,min(1,x))))
def mins(t):
    h,m=map(int,t.split(":")); return h*60+m
def overlap(a,b): return max(mins(a.start),mins(b.start))<min(mins(a.end),mins(b.end))
def compatible(sr,dr,sf,df):
    if sr.resource_type!=dr.resource_type:return False,0,["Resource type mismatch"]
    if sr.temperature<dr.temperature:return False,0,[f"Supply temperature {sr.temperature:g}°C is below demand minimum {dr.temperature:g}°C"]
    if not overlap(sr,dr):return False,0,["Operating windows do not overlap"]
    km=dist(sf,df); q=min(sr.quantity,dr.quantity); proximity=max(0,1-km/25)
    score=min(100,round(38+25*proximity+20*sr.reliability+10*(q/max(sr.quantity,dr.quantity)),1))
    reasons=["Resource type compatible","Temperature requirement met","Time window overlaps",f"Distance {km:.2f} km",f"Reliability {sr.reliability*100:.0f}%"]
    return True,score,reasons
def impact(q,km,unit):
    factor={"kWh":0.22,"kg":0.12,"L":0.00035,"m3":0.35}.get(unit,0.10)
    co2=q*factor; savings=max(0,q*(0.12 if unit=="kWh" else 0.06)-q*km*0.015)
    return round(co2,2),round(savings,2)

def seed(s):
    if s.query(Factory).count()>0:return
    fs=[
      Factory(name="Apex Steel Works",industry="Steel",location="Pune MIDC",lat=18.6298,lon=73.7997,email="ops@apex.demo",status="ACTIVE"),
      Factory(name="GreenBite Foods",industry="Food Processing",location="Pune MIDC",lat=18.6180,lon=73.8065,email="ops@greenbite.demo",status="ACTIVE"),
      Factory(name="Nova Chemicals",industry="Chemical",location="Pune MIDC",lat=18.6410,lon=73.8120,email="ops@nova.demo",status="ACTIVE"),
      Factory(name="WeaveTex",industry="Textile",location="Pune MIDC",lat=18.6300,lon=73.8200,email="ops@weavetex.demo",status="ACTIVE")]
    s.add_all(fs);s.flush()
    rs=[
      Resource(factory_id=fs[0].id,direction="SUPPLY",resource_type="WASTE_HEAT",quantity=500,unit="kWh",temperature=180,start="14:00",end="17:00",reliability=.87),
      Resource(factory_id=fs[1].id,direction="DEMAND",resource_type="WASTE_HEAT",quantity=350,unit="kWh",temperature=150,start="14:00",end="16:00",reliability=.90),
      Resource(factory_id=fs[2].id,direction="SUPPLY",resource_type="WASTE_STEAM",quantity=250,unit="kg",temperature=165,start="14:00",end="17:00",reliability=.88),
      Resource(factory_id=fs[3].id,direction="DEMAND",resource_type="WASTE_STEAM",quantity=180,unit="kg",temperature=140,start="15:00",end="17:00",reliability=.85),
      Resource(factory_id=fs[0].id,direction="SUPPLY",resource_type="REUSABLE_WATER",quantity=800,unit="L",temperature=30,start="10:00",end="18:00",reliability=.82),
      Resource(factory_id=fs[3].id,direction="DEMAND",resource_type="REUSABLE_WATER",quantity=600,unit="L",temperature=40,start="11:00",end="18:00",reliability=.88)]
    s.add_all(rs);s.flush(); random.seed(42); today=date.today()
    for r in rs:
        for i in range(21,0,-1):
            base=r.quantity*(0.82+0.20*random.random()); s.add(ResourceHistory(resource_id=r.id,day=today-timedelta(days=i),quantity=round(base,2)))
    s.commit()

s=SessionLocal()
try: seed(s)
finally:s.close()

@app.get("/health")
def health(): return {"status":"healthy","project":"EcoLoop","version":"3.1"}

@app.post("/api/login")
def login(x:LoginIn,s:Session=Depends(db)):
    users={"admin":{"password":"admin123","role":"ADMIN","name":"Admin User"},"factory":{"password":"factory123","role":"FACTORY","name":"Factory Operator"}}
    u=users.get(x.username)
    if not u or u["password"]!=x.password: raise HTTPException(401,"Invalid username or password")
    factory_id=None
    if x.username=="factory":
        f=s.query(Factory).filter(Factory.status=="ACTIVE").order_by(Factory.id).first()
        factory_id=f.id if f else None
        u["name"]=f.name if f else "Factory Operator"
    return {"token":"demo-"+x.username,"role":u["role"],"name":u["name"],"factory_id":factory_id}

@app.get("/api/system/status")
def system_status(s:Session=Depends(db)):
    db_ok=False
    try: s.execute(__import__('sqlalchemy').text("SELECT 1")); db_ok=True
    except Exception: db_ok=False
    rf_ok=False; ortools_ok=False
    try: RandomForestRegressor(n_estimators=2,random_state=1); rf_ok=True
    except Exception: pass
    try: ortools_ok=pywraplp.Solver.CreateSolver("SCIP") is not None
    except Exception: pass
    return {"role_based_login":True,"postgresql":db_ok,"random_forest":rf_ok,"ortools":ortools_ok,"openstreetmap":True,"dynamic_dashboard":True}

@app.get("/api/factories")
def factories(s:Session=Depends(db)): return [dto_factory(f) for f in s.query(Factory).order_by(Factory.id).all()]
@app.post("/api/factories")
def add_factory(x:FactoryIn,s:Session=Depends(db)):
    f=Factory(**x.model_dump(),status="PENDING");s.add(f);s.commit();s.refresh(f);return dto_factory(f)
@app.patch("/api/factories/{id}/{action}")
def factory_action(id:int,action:str,s:Session=Depends(db)):
    f=s.get(Factory,id)
    if not f: raise HTTPException(404,"Factory not found")
    if action not in ("approve","reject"): raise HTTPException(400,"Invalid action")
    f.status="ACTIVE" if action=="approve" else "REJECTED";s.commit();return dto_factory(f)

@app.get("/api/resources")
def resources(s:Session=Depends(db)): return [dto_resource(r,s) for r in s.query(Resource).order_by(Resource.id.desc()).all()]
@app.post("/api/resources")
def add_resource(x:ResourceIn,s:Session=Depends(db)):
    f=s.get(Factory,x.factory_id)
    if not f: raise HTTPException(404,"Factory not found")
    if f.status!="ACTIVE": raise HTTPException(400,"Factory must be approved before publishing resources")
    r=Resource(**x.model_dump());s.add(r);s.flush()
    for i,mult in [(2,.92),(1,.98),(0,1.0)]: s.add(ResourceHistory(resource_id=r.id,day=date.today()-timedelta(days=i),quantity=round(x.quantity*mult,2)))
    s.commit();s.refresh(r);return dto_resource(r,s)

@app.get("/api/matches")
def get_matches(s:Session=Depends(db)):
    ms=s.query(Match).order_by(Match.id.desc()).all(); fs={f.id:f.name for f in s.query(Factory).all()}
    return [{"id":m.id,"supplier":m.supplier,"supplier_name":fs.get(m.supplier),"consumer":m.consumer,"consumer_name":fs.get(m.consumer),"resource":m.resource,"unit":m.unit,"quantity":m.quantity,"distance":m.distance,"score":m.score,"co2":m.co2,"savings":m.savings,"reasons":m.reasons.split("|") if m.reasons else [],"run_id":m.run_id,"created":m.created.isoformat()} for m in ms]

def compute_candidates(s):
    supplies=s.query(Resource).filter(Resource.direction=="SUPPLY").all(); demands=s.query(Resource).filter(Resource.direction=="DEMAND").all(); fs={f.id:f for f in s.query(Factory).all()}; c=[]
    for sr in supplies:
        sf=fs.get(sr.factory_id)
        if not sf or sf.status!="ACTIVE":continue
        for dr in demands:
            df=fs.get(dr.factory_id)
            if not df or df.status!="ACTIVE" or sf.id==df.id:continue
            ok,score,reasons=compatible(sr,dr,sf,df)
            if ok:c.append({"supplier":sf.id,"consumer":df.id,"resource":sr.resource_type,"unit":sr.unit,"supply":sr.quantity,"demand":dr.quantity,"distance":round(dist(sf,df),2),"score":score,"reasons":reasons})
    return c

def optimize(c):
    if not c:return []
    solver=pywraplp.Solver.CreateSolver("SCIP") or pywraplp.Solver.CreateSolver("CBC")
    vars=[solver.NumVar(0,min(x["supply"],x["demand"]),f"x{i}") for i,x in enumerate(c)]
    # Prevent overselling a supply resource and over-consuming a demand resource.
    supply_groups={}; demand_groups={}
    for i,x in enumerate(c):
        supply_groups.setdefault((x["supplier"],x["resource"]),[]).append(i); demand_groups.setdefault((x["consumer"],x["resource"]),[]).append(i)
    for inds in supply_groups.values(): solver.Add(sum(vars[i] for i in inds)<=c[inds[0]]["supply"])
    for inds in demand_groups.values(): solver.Add(sum(vars[i] for i in inds)<=c[inds[0]]["demand"])
    obj=solver.Objective()
    for v,x in zip(vars,c): obj.SetCoefficient(v,1000+x["score"])
    obj.SetMaximization(); solver.Solve()
    return [{**x,"quantity":round(v.solution_value(),2)} for v,x in zip(vars,c) if v.solution_value()>0.01]

@app.post("/api/run-ecoloop")
def run_ecoloop(s:Session=Depends(db)):
    candidates=compute_candidates(s); chosen=optimize(candidates); run_id=datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    for old in s.query(Match).all(): s.delete(old)
    reused=co2=savings=0
    for x in chosen:
        c,sv=impact(x["quantity"],x["distance"],x["unit"]); reused+=x["quantity"];co2+=c;savings+=sv
        s.add(Match(supplier=x["supplier"],consumer=x["consumer"],resource=x["resource"],unit=x["unit"],quantity=x["quantity"],distance=x["distance"],score=x["score"],co2=c,savings=sv,reasons="|".join(x["reasons"]),run_id=run_id))
    s.add(Run(run_id=run_id,matches=len(chosen),reused=round(reused,2),co2=round(co2,2),savings=round(savings,2)));s.commit()
    return {"run_id":run_id,"matches":len(chosen),"reused":round(reused,2),"co2":round(co2,2),"savings":round(savings,2),"status":"completed"}

@app.get("/api/runs")
def runs(s:Session=Depends(db)): return [{"run_id":r.run_id,"created":r.created.isoformat(),"matches":r.matches,"reused":r.reused,"co2":r.co2,"savings":r.savings} for r in s.query(Run).order_by(Run.id.desc()).limit(10)]

def forecast_one(rid,s):
    r=s.get(Resource,rid); hist=s.query(ResourceHistory).filter(ResourceHistory.resource_id==rid).order_by(ResourceHistory.day).all()
    if not r:return None
    y=[h.quantity for h in hist]
    if len(y)>=7:
        X=[[i] for i in range(len(y))]; model=RandomForestRegressor(n_estimators=180,random_state=42,min_samples_leaf=1).fit(X,y); pred=float(model.predict([[len(y)+1]])[0]); model_name="Random Forest"
    else: pred=float(sum(y[-5:])/max(1,len(y[-5:]))) if y else r.quantity; model_name="Rolling mean"
    pred=max(0,pred); spread=max(pred*.08,0.01)
    return {"resource_id":r.id,"factory_id":r.factory_id,"resource_type":r.resource_type,"direction":r.direction,"unit":r.unit,"today":r.quantity,"predicted":round(pred,2),"low":round(max(0,pred-spread),2),"high":round(pred+spread,2),"reliability":round(r.reliability*100,1),"model":model_name}
@app.get("/api/forecasts")
def forecasts(s:Session=Depends(db)): return [x for r in s.query(Resource).order_by(Resource.id).all() if (x:=forecast_one(r.id,s))]
@app.post("/api/forecast/tomorrow")
def forecast_tomorrow(s:Session=Depends(db)): rows=forecasts(s); return {"date":(date.today()+timedelta(days=1)).isoformat(),"rows":rows,"count":len(rows)}
@app.get("/api/history/{resource_id}")
def history(resource_id:int,s:Session=Depends(db)):
    r=s.get(Resource,resource_id)
    if not r: raise HTTPException(404,"Resource not found")
    return [{"date":h.day.isoformat(),"quantity":h.quantity} for h in s.query(ResourceHistory).filter(ResourceHistory.resource_id==resource_id).order_by(ResourceHistory.day).all()]

@app.post("/api/what-if")
def what_if(x:WhatIf,s:Session=Depends(db)):
    rs=s.query(Resource).filter(Resource.factory_id==x.factory_id,Resource.direction=="SUPPLY").all()
    if not rs:return {"error":"No supply resource for this factory"}
    original=sum(r.quantity for r in rs); simulated=original*(1-x.reduction/100); current=sum(m.quantity for m in s.query(Match).filter(Match.supplier==x.factory_id).all()); projected=min(current,simulated)
    return {"original":round(original,2),"simulated":round(simulated,2),"current_reuse":round(current,2),"projected_reuse":round(projected,2),"reduction":x.reduction}

@app.get("/api/dashboard")
def dashboard(s:Session=Depends(db)):
    fs=s.query(Factory).all();rs=s.query(Resource).all();ms=s.query(Match).all(); active=[f for f in fs if f.status=="ACTIVE"]
    supply=sum(r.quantity for r in rs if r.direction=="SUPPLY"); demand=sum(r.quantity for r in rs if r.direction=="DEMAND"); types={}
    for r in rs: types[r.resource_type]=types.get(r.resource_type,0)+r.quantity
    return {"total":len(fs),"active":len(active),"pending":sum(f.status=="PENDING" for f in fs),"resources":len(rs),"matches":len(ms),"supply":round(supply,2),"demand":round(demand,2),"reused":round(sum(m.quantity for m in ms),2),"co2":round(sum(m.co2 for m in ms),2),"savings":round(sum(m.savings for m in ms),2),"resource_distribution":[{"name":k,"value":round(v,2)} for k,v in sorted(types.items(),key=lambda z:-z[1])],"updated":datetime.utcnow().isoformat()}
@app.get("/api/impact")
def impact_data(s:Session=Depends(db)):
    ms=s.query(Match).all(); by={}
    for m in ms: by[m.resource]=by.get(m.resource,0)+m.quantity
    return {"reused":round(sum(m.quantity for m in ms),2),"co2":round(sum(m.co2 for m in ms),2),"savings":round(sum(m.savings for m in ms),2),"by_resource":[{"name":k,"value":round(v,2)} for k,v in by.items()]}

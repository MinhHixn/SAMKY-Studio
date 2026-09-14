// Development-only fixture server. No model, graph database, or external calls.
// VITE_API_BASE_URL=http://127.0.0.1:5181 npm run dev -- --port 5174
import http from 'node:http'
const names=['Maya Chen','Oliver Reed','Sofia Alvarez','James Park','Amara Okafor','Noah Laurent','Isabel Costa','Liam Morgan']
const roles=['Community organizer','Product designer','Local journalist','Small business owner','Researcher','Student','Policy analyst','Teacher']
const graph={nodes:Array.from({length:64},(_,i)=>({uuid:'node-'+i,name:names[i]||'Community '+(i+1),labels:['Entity',['Resident','Organization','Media'][i%3]],summary:'A fictional participant used only to verify the studio interface.'})),edges:Array.from({length:112},(_,i)=>({uuid:'edge-'+i,source_node_uuid:'node-'+i%64,target_node_uuid:'node-'+(i*7+11)%64,name:'INTERACTS_WITH'}))}
let mode='running',started=false,prepared=false,rounds=60,platform='parallel',envAlive=true,requests=[],reportDone=true
let runtime={mode:'offline',model:'qwen2.5:7b',base_url:'http://localhost:11434/v1',has_api_key:false}
const report=()=>({report_id:'report_fixture',simulation_id:'sim_fixture',graph_id:'graph_fixture',status:reportDone?'completed':'generating',outline:{title:'When a city changes how it moves',summary:'A simulation of public reactions to a proposed car-free city center. This is a UI test fixture, not a model-generated result.'},markdown_content:'# What we observed\n\nResidents formed several distinct communities around accessibility, local commerce, and public space.\n\n## The first reactions\n\n**Community organizers** brought the conversation back to everyday routines. Business owners asked for practical delivery access.\n\n## What changed\n\n- Specific implementation details encouraged more constructive discussion.\n- Local stories travelled further than abstract claims.\n- Opinions continued to differ across communities.\n\n## The next question\n\nInterview the agents to understand which information changed their perspective.'})
const project={project_id:'project_fixture',name:'A city without cars',graph_id:'graph_fixture',status:'graph_completed',simulation_requirement:'How might residents respond to a car-free city center?'}
http.createServer(async(req,res)=>{
  res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Headers','Content-Type');res.setHeader('Access-Control-Allow-Methods','GET,POST,OPTIONS')
  if(req.method==='OPTIONS'){res.writeHead(204);res.end();return}
  const path=new URL(req.url,'http://localhost').pathname;let raw='';for await(const chunk of req)raw+=chunk;let body={};try{body=JSON.parse(raw)}catch{}
  const send=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(status>=400?{success:false,error:data}:{success:true,data}))}
  if(path==='/__qa'){if(req.method==='POST'){mode=body.mode||mode;reportDone=body.reportDone??reportDone;envAlive=body.envAlive??envAlive;if(body.reset){started=false;prepared=false;requests=[]}}return send({mode,started,rounds,platform,requests})}
  requests.push({path,method:req.method,...(body.rounds?{rounds:body.rounds}:{}),...(body.interviews?{ids:body.interviews.map(i=>i.agent_id),platform:body.platform}:{}),...(path==='/api/runtime'&&req.method==='POST'?{model:body.model,keyRemoved:body.api_key===''}:{})})
  if(path==='/api/runtime'){if(req.method==='POST')runtime={...runtime,...body,has_api_key:!!body.api_key};const {api_key,...safe}=runtime;return send(safe)}
  if(path==='/api/runtime/models')return body.api_key==='invalid'?send('The endpoint rejected the API key.',400):send({models:['qwen2.5:7b','local-fixture-model']})
  if(path==='/api/simulation/history')return send([{...project,project_name:project.name,simulation_id:'sim_fixture',created_at:'2026-09-13T11:00:00',report_id:'report_fixture'}])
  if(path==='/api/graph/ontology/generate')return send(project)
  if(path==='/api/graph/project/project_fixture')return send(project)
  if(path==='/api/graph/data/graph_fixture')return send(graph)
  if(path==='/api/simulation/list')return send(started?[{simulation_id:'sim_fixture'}]:[])
  if(path==='/api/simulation/create')return send({simulation_id:'sim_fixture'})
  if(path==='/api/simulation/sim_fixture')return send({...project,simulation_id:'sim_fixture',status:started?'running':prepared?'ready':'created',enable_reddit:platform!=='twitter',enable_twitter:platform!=='reddit'})
  if(path==='/api/simulation/prepare/status')return send({status:prepared?'ready':'not_started',progress:prepared?100:0})
  if(path==='/api/simulation/prepare'){prepared=true;return send({task_id:'prepare_fixture'})}
  if(path==='/api/simulation/start'){started=true;rounds=body.rounds;platform=body.platform;return send({runner_status:'running',total_rounds:rounds})}
  if(path==='/api/simulation/sim_fixture/run-status')return send({runner_status:started?mode:'idle',current_round:28,reddit_current_round:28,twitter_current_round:32,total_rounds:rounds,error:mode==='failed'?'Fixture model connection failed':null})
  if(path==='/api/simulation/stop'){mode='stopped';return send({runner_status:'stopped'})}
  if(path==='/api/report/generate')return send({report_id:'report_fixture',simulation_id:'sim_fixture',task_id:'report_task'})
  if(path==='/api/report/report_fixture'||path==='/api/report/by-simulation/sim_fixture')return send(report())
  if(path==='/api/report/report_fixture/progress')return send({status:reportDone?'completed':'generating',progress:reportDone?100:45})
  if(path==='/api/simulation/sim_fixture/profiles/realtime')return send({profiles:names.map((name,i)=>({user_id:i,name,username:name.toLowerCase().replaceAll(' ','_'),profession:roles[i],bio:'A fictional profile for checking conversations and agent selection.',country:'Test community'}))})
  if(path==='/api/simulation/env-status')return send({env_alive:envAlive})
  if(path==='/api/simulation/close-env'){envAlive=false;return send({success:true})}
  if(path==='/api/simulation/interview/batch')return setTimeout(()=>send({result:{results:Object.fromEntries(body.interviews.map(i=>[`${body.platform}_${i.agent_id}`,{agent_id:i.agent_id,response:`I paid most attention to **accessibility** and the experiences of people in my neighborhood.\n\nSpecific details about delivery access changed my initial reaction. This is a fixture reply from ${names[i.agent_id]}.`}]))}}),650)
  if(path==='/api/report/chat')return send({response:'The simulation suggests that concrete implementation details shaped the discussion. This is a fixture analyst reply.'})
  send('Fixture route not found: '+path,404)
}).listen(5181,'127.0.0.1',()=>console.log('SAM fixture API: http://127.0.0.1:5181 (synthetic data only)'))

const express = require("express")
const app = express()
const PORT = process.env.PORT || 3000
const poolName = process.env.POOL_NAME 
const realeaseId = process.env.RELEASE_ID

let chaosMode = null

app.get("/version", (req, res) => {
  if(chaosMode === "error") {
    console.log('CHAOS 500; Intentionally failling request');
    return res.status(500).json({ error: `Simulated error due to chaos mode.${chaosMode}` })
  }
  if(chaosMode === "timeout") {
    console.log('CHAOS TIMEOUT; Intentionally delaying response');
    return setTimeout(() => {
      res.status(200).json({ version: "delayed" })
    }, 10000) // 10 seconds delay
  }

  res.set({
    'X-App-Pool': poolName || 'default-pool',
    'X-Release-Id': realeaseId || 'no-release-id'
  })

  res.status(200).json({ 
    service: "NodeJS BLUE/GREEN APP",
    release: realeaseId,
    pool: poolName,
    message: "Hello From HNGi13"

  })
})

app.post('/chaos/start', (req, res) => {
    // logic to stimulate downtime
    chaosMode = req.query.mode || "error"
    console.log(`CHAOS STARTED!!. Chaos mode set to: ${chaosMode}`)
    res.status(200).json({ status: "Chaos started", mode: chaosMode })
})

app.post('/chaos/stop', (req, res) => {
    // logic to stop downtime simulation
    chaosMode = null
    console.log(`CHAOS STOPPED!!. Chaos mode set to: ${chaosMode}`)
    res.status(200).json({ status: "Chaos stopped", mode: chaosMode })
})

app.get("/healthz", (req, res) => {
    //process liveness probe
    if (chaosMode !== null) {
        console.log(chaosMode);
        
        return res.status(200).json({ status: "ERROR", message: "Service is unhealthy due to chaos mode." })
    }
    console.log(chaosMode);
    
    return res.status(200).json({ status: "OK", message: "Service is healthy." })
})

app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`)
})
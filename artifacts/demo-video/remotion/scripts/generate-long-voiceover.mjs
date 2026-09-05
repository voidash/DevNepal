import {spawn} from 'node:child_process';
import {mkdir, unlink} from 'node:fs/promises';
import path from 'node:path';

const kalaBinary = process.env.KALA_TTS_BIN || 'uvx';
const kalaSpeaker = process.env.KALA_TTS_SPEAKER || 'kala';
const kalaSpeed = process.env.KALA_TTS_LONG_SPEED || '1.10';
const ffmpegBinary = process.env.FFMPEG_BIN || 'ffmpeg';
const usesUvx = !process.env.KALA_TTS_BIN;
const chapterSpeeds = {
  '05-public-profile.mp3': '1.20',
  '06-ministry-create.mp3': '1.12',
  '07-live-refresh.mp3': '1.45',
  '08-github-proof.mp3': '1.22',
  '10-resilience-close.mp3': '1.32',
};

const chapters = [
  [
    '01-public-entry.mp3',
    `यो प्रदर्शन डेभनेपालको सार्वजनिक प्रवेशबाट सुरु हुन्छ। पहिलो पटक आउने आगन्तुकलाई खाता बनाउन, पासवर्ड सम्झन वा कुनै लामो परिचय फाराम भर्न बाध्य पारिएको छैन। मुख्य उद्देश्य नागरिक, विद्यार्थी, डिजाइनर, अनुवादक र सफ्टवेयर विकासकर्तालाई सरकारले सार्वजनिक रूपमा सहयोग मागेको काम छिटो बुझाउनु हो। माथिको मेनु छोटो राखिएको छ। सरकारी परियोजना र योगदान गर्ने तरिका मुख्य बाटा हुन्। नेपाली र अंग्रेजी दुवै भाषा यही ठाउँबाट बदल्न सकिन्छ। अगाडिको मुख्य सन्देशले मञ्चले के गर्छ भन्ने स्पष्ट गर्छ, र तलका वास्तविक जस्ता नमुना तथ्याङ्कले खाली prototype को अनुभूति हुन दिँदैन। यहाँ देखिने प्रत्येक परियोजनामा जिम्मेवार निकाय, परियोजनाको अवस्था र योगदानको प्रकृति छ। आगन्तुकलाई पहिले अर्थपूर्ण जानकारी दिइन्छ, त्यसपछि मात्र अर्को कदम प्रस्ताव गरिन्छ। यही visitor-first सिद्धान्तले अनावश्यक admin, account setting र आन्तरिक workflow लाई सार्वजनिक navigation बाट हटाएको छ। यस चरणमा हामी केवल सार्वजनिक काम खोज्दैछौँ; कुनै व्यक्तिगत data पठाइएको छैन र कुनै GitHub अनुमति मागिएको छैन।`,
  ],
  [
    '02-project-discovery.mp3',
    `अब सरकारी परियोजनाको सूची खोलिएको छ। यो पृष्ठ catalogue जस्तो देखिए पनि यसको काम केवल कार्ड देखाउनु होइन। आगन्तुकले कुन काम आधिकारिक हो, कसले प्रकाशन गरेको हो, अहिले योगदान खुला छ कि छैन, र योगदान प्राविधिक हो कि गैरप्राविधिक हो भन्ने तुरुन्त बुझ्नुपर्छ। त्यसैले अत्यधिक badge, duplicate metadata र लामो व्याख्या हटाएर निर्णय गर्न आवश्यक कुरा मात्र राखिएको छ। नमुना data पनि प्रस्तुतीकरणका लागि अर्थपूर्ण बनाइएको छ। नागरिक सहायता निर्देशिका वास्तविक सार्वजनिक repository सँग जोडिएको मुख्य उदाहरण हो। त्यससँगै अन्य सरकारी समस्याका उदाहरणले यो केवल एउटा project का लागि बनाइएको hardcoded page होइन भन्ने देखाउँछन्। सूचीमा नेपाली शीर्षक र विवरण पढ्न मिल्छ, तर GitHub को repository नाम, issue number र technical label जस्ता source identifiers अनुवाद गरेर बिगारिँदैनन्। अब हामी नागरिक सहायता निर्देशिका खोल्छौँ। परियोजना रोज्दा आगन्तुकले मन्त्रालयको नाम, सार्वजनिक उद्देश्य, अपेक्षित परिणाम र योगदान सुरु गर्ने स्थान एउटै flow मा पाउँछ। यहाँ account बिना browsing सम्भव छ। खोजबाट detail मा पुग्ने सबै link वास्तविक Django route हुन्; packaged mockup होइनन्। यदि कुनै listing pause वा complete भयो भने पनि त्यसको इतिहास हराउँदैन, तर खुला योगदानको संकेत स्पष्ट रूपमा बदलिन्छ। यसरी सार्वजनिक discovery ले गलत अपेक्षा घटाउँछ र contributor लाई कुन काममा समय लगाउने भन्ने राम्रो निर्णय गर्न दिन्छ।`,
  ],
  [
    '03-project-github.mp3',
    `यो नागरिक सहायता निर्देशिकाको परियोजना विवरण हो। पृष्ठको माथिल्लो भागले परियोजनाको समस्या, जिम्मेवार विभाग र contribution को सीमा बुझाउँछ। त्यसपछि GitHub बाट synchronized गरिएको सार्वजनिक activity आउँछ। महत्वपूर्ण कुरा के हो भने डेभनेपाल code hosting platform बन्न खोजेको छैन। code, branch, discussion, assignment र pull request को source of truth GitHub नै हो। डेभनेपालले त्यसको सार्वजनिक snapshot लाई सरकारी project context सँग जोड्छ। यहाँ repository को स्पष्ट link र अन्तिम synchronization समय देखिन्छ। समय देखाउनु इमानदार design हो, किनकि snapshot लाई real-time भनेर दाबी गर्नु गलत हुन्छ। अहिले चार खुला issues छन्। नम्बर सातले छात्रवृत्ति सम्बन्धी नेपाली eligibility text थप्ने काम देखाउँछ। नम्बर आठले स्वास्थ्य सहायता सम्पर्क विवरण आधिकारिक source सँग जाँच्ने काम देखाउँछ। नम्बर नौले keyboard-first workflow document गर्ने काम देखाउँछ। नम्बर एघार यही demo का लागि GitHub मा सिर्जना गरिएको synchronization proof हो। प्रत्येक issue को title र number DevNepal मा देखिन्छ, र पूर्ण detail छुट्टै route मा खुल्छ। त्यसै पृष्ठमा pull request नम्बर दस खुला रहेको देखिन्छ। मन्त्रालयले submitted code लाई complete contribution भनेर तुरुन्त दाबी गर्दैन; open pull request लाई review मा रहेको activity भनेर मात्र देखाउँछ। contributor section मा public GitHub identity र repository contribution count छ। निजी email, access token वा private repository data यहाँ आउँदैन। यो snapshot GitHub App installation token बाट server-side मा ल्याइन्छ, user OAuth बाट होइन। त्यसैले साधारण visitor लाई GitHub sign-in गर्न आवश्यक छैन। मन्त्रालयले repository जोड्दा public repository मात्र चयन गर्छ, र service ले GitHub metadata बाट full name र privacy फेरि जाँचेर मात्र issue, pull request र contributor projection replace गर्छ। refresh सफल भए पुरानो snapshot atomically नयाँ data ले बदलिन्छ। बीचमा error आए अधुरो आधा data public page मा आउँदैन। यही भागले visitor लाई project को brochure मात्र होइन, अहिले काम कहाँ अड्किएको छ र योगदानको वास्तविक entry point के हो भन्ने देखाउँछ।`,
  ],
  [
    '04-issue-handoff.mp3',
    `अब issue नम्बर एघार खोलिएको छ। सूचीबाट बाहिर ननिस्की visitor ले issue को पूरा उद्देश्य, description, labels, author, comment count र acceptance criteria पढ्न सक्छ। Markdown सुरक्षित HTML मा render हुन्छ, त्यसैले heading र list पढ्न सजिलो हुन्छ तर arbitrary script चल्दैन। यो issue को लक्ष्य डेभनेपालको GitHub synchronization प्रमाणित गर्नु हो। acceptance criteria ले GitHub मा issue open रहनुपर्ने, DevNepal मा सही number र title देखिनुपर्ने, र contributor लाई आधिकारिक GitHub page मा पठाउनुपर्ने स्पष्ट गर्छ। यस्तो detail आवश्यक छ, किनकि केवल “contribute” button देखाएर user लाई बाहिर पठाउनु राम्रो onboarding होइन। पहिले काम बुझ्न दिइन्छ, त्यसपछि Start contributing on GitHub भन्ने स्पष्ट action आउँछ। अब हामी Brave को अर्को tab मा वास्तविक GitHub issue खोल्छौँ। URL voidash slash civic-help-directory slash issues slash eleven हो। title, number र body DevNepal मा देखिएको snapshot सँग मिल्छ। GitHub मा नै assignment, comments, branch reference र pull request बनाउने काम हुन्छ। DevNepal ले यी interaction नक्कल गर्दैन र visitor को GitHub credential लिँदैन। यस सीमाले security र product दुवै सरल बनाउँछ। यदि issue GitHub मा update भयो भने मन्त्रालयको refresh पछि नयाँ public snapshot आउँछ। यदि GitHub केही समय उपलब्ध भएन भने पुरानो valid snapshot र direct source link बाँकी रहन्छ। त्यसैले visitor सँग काम सुरु गर्ने बाटो हराउँदैन। यो handoff flow को सफलता भनेको DevNepal भित्र सबै GitHub feature बनाउनु होइन; सही context दिई सही source मा सुरक्षित रूपमा पुर्‍याउनु हो।`,
  ],
  [
    '05-public-profile.mp3',
    `Issue र project बाट contributor को नाम खोल्दा यो public GitHub profile देखिन्छ। यो पुरानो DevNepal résumé वा छुट्टै social network होइन। नाम, avatar, bio, location, company, public repository count र follower count जस्ता GitHub ले सार्वजनिक रूपमा दिएको सीमित data मात्र राखिएको छ। तल tracked public repository मा देखिएको contribution summary आउँछ। यसले मन्त्रालयलाई व्यक्ति वास्तवमै कुन सार्वजनिक repository मा देखिएको छ भन्ने context दिन्छ, तर commit count लाई quality score वा सरकारी endorsement बनाउँदैन। profile cached snapshot भएकाले synchronization समय देखाइन्छ। GitHub को मूल profile मा जाने link पनि सधैँ उपलब्ध छ। “More GitHub profiles” क्षेत्रमा अन्य सार्वजनिक community profiles देखाइएका छन्, ताकि page एक जना demo user मात्र hardcode गरिएको जस्तो नहोस्। कसैले DevNepal account नबनाए पनि public GitHub activity बाट profile खुल्न सक्छ। कसैको private email, access token, private contribution वा hidden organization membership देखाइँदैन। यसरी contributor identity सरल, प्रमाणयोग्य र GitHub-first रहन्छ।`,
  ],
  [
    '06-ministry-create.mp3',
    `अब हामी ministry publisher को भूमिकामा जान्छौँ। sign-in पछि publisher लाई member profile वा super-admin console मा नपठाई सिधै आफ्नो publishing dashboard मा ल्याइन्छ। त्यहाँ उसले आफ्नो मन्त्रालयका draft, review र published projects मात्र देख्छ। Create project खोल्दा bilingual authoring form आउँछ। demo का लागि सानो Fill demo details button राखिएको छ। यो production automation होइन; presentation मा समय बचाउन realistic sample values भर्ने helper हो। button थिचेपछि अंग्रेजी र नेपाली title, summary, problem statement, expected outcome, participation guidance र ministry response commitment भरिन्छन्। publisher ले save गर्नु अघि सबै field review गर्नुपर्छ। repository URL मा वास्तविक voidash slash civic-help-directory राखिएको छ। issue tracker URL पनि त्यही repository को issues page हो। default branch main र licence MIT छन्। contribution mode, difficulty र effort band ले visitor लाई कामको आकार बुझाउँछन्। deadline र response time ले मन्त्रालयको जिम्मेवारी स्पष्ट गर्छ। demo-fill ले submit गर्दैन, त्यसैले operator ले गल्तीले duplicate project प्रकाशित गर्दैन। नयाँ project बनेपछि repository connection GitHub App installation को accessible repository सँग verify गरिन्छ। form मा कुनै GitHub personal token राखिँदैन। server ले App credential बाट repository list पढ्छ र public metadata match भएपछि मात्र binding स्वीकार्छ। यो अलगाव महत्वपूर्ण छ: publisher ले project context व्यवस्थापन गर्छ, GitHub ले code collaboration व्यवस्थापन गर्छ। हामीले frontend घटाउँदा readiness, deep admin tabs र असम्बन्धित member features सार्वजनिक menu बाट हटाएका छौँ, तर backend lifecycle delete गरेका छैनौँ। demo मा आवश्यक create, edit, publish र repository activity paths भने वास्तविक छन्। यो screen ले team लाई design मात्र होइन, Django form validation, authorization, bilingual content र repository integration एउटै flow मा जोडिएको देखाउँछ।`,
  ],
  [
    '07-live-refresh.mp3',
    `अब existing published project को ministry workspace खोलिएको छ। repository card मा voidash slash civic-help-directory, sync state, अन्तिम synchronized समय, चार issues, pull request नम्बर दस र contributor summary देखिन्छ। पहिले यो data refresh गर्न terminal command चलाउनुपर्थ्यो। त्यही नै वास्तविक gap थियो। अब publisher ले Refresh GitHub activity button थिच्न सक्छ। यो साधारण GET link होइन; CSRF protected POST हो। route मा project slug र repository id दुवै हुन्छन्, र server ले repository वास्तवमै यही project सँग जोडिएको, public, active र stopped नभएको जाँच गर्छ। signed-in user सोही active ministry को verified publisher हुनुपर्छ र privileged MFA policy पास गर्नुपर्छ। अर्को ministry को publisher ले id अनुमान गरे पनि resource भेटिएको जानकारी पाउँदैन। button थिचेपछि प्रति repository साठी second को atomic cache reservation लिइन्छ। double click वा दुई publisher tabs ले एकै पटक धेरै GitHub API requests पठाउन पाउँदैनन्। त्यसपछि GitHub App client ले metadata, open issues, open pull requests, contributors र सीमित public profile data ल्याउँछ। service ले repository private नभएको र full name binding सँग मिलेको फेरि जाँच गर्छ। सफल response पूरा भएपछि मात्र database transaction भित्र snapshot rows update हुन्छन्। परिणाममा issue, pull request र contributor count सहित audit event लेखिन्छ र नयाँ Last synchronized समय page मा देखिन्छ। GitHub timeout, credential error वा invalid response आए सुरक्षित generic message देखाइन्छ; upstream secret detail browser मा आउँदैन। पहिलेको राम्रो snapshot delete हुँदैन। failure पनि audit मा safe error code सहित रहन्छ। अहिले video मा button click, केही second को वास्तविक provider request र सफल refresh message देखिन्छ। यसलाई continuous real-time stream भन्नु हुँदैन। यो publisher-triggered live refresh हो, जसले timestamped public snapshot बनाउँछ। public visitors का हरेक page load मा GitHub call नगर्नु जानाजानी हो; त्यसो गरे page ढिलो, provider-dependent र abuse गर्न सजिलो हुन्थ्यो।`,
  ],
  [
    '08-github-proof.mp3',
    `अब synchronization को source evidence फेरि GitHub मा जाँचिन्छ। Issues सूचीमा demo synchronization issue नम्बर एघार खुला छ। DevNepal project page मा देखिएको number र title यहीँबाट आएको हो। पुराना मुद्दा सात, आठ र नौ पनि दुवै ठाउँमा एउटै रूपमा देखिन्छन्। Pull requests tab मा नम्बर दस खुला छ र keyboard-only contribution workflow document गर्ने काम review मा छ। Ministry workspace ले यसलाई finished वा accepted भनेर गलत रूपमा देखाएको छैन। source मा open छ भने projection मा open नै छ। contributor count पनि repository को public contributors endpoint बाट आएको हो। यस cross-check को उद्देश्य screenshot सजाउनु होइन; end-to-end boundary प्रमाणित गर्नु हो। GitHub मा issue create वा update हुन्छ, publisher refresh चलाउँछ, Django ले validated public snapshot राख्छ, visitor ले आफ्नो भाषामा context पढ्छ, र काम गर्न GitHub को canonical URL मा फर्कन्छ। user OAuth हटाइए पनि यो flow चल्छ, किनकि integration GitHub App installation आधारित छ। repository private भयो वा App access हट्यो भने service ले नयाँ public data publish गर्दैन। stale snapshot सँग failure note रहन्छ र operator ले direct GitHub link जाँच्न सक्छ। यसरी demo को दाबी specific र परीक्षणयोग्य छ: DevNepal GitHub को replacement होइन; सरकारी project discovery र ministry accountability को public layer हो।`,
  ],
  [
    '09-mobile-nepali.mp3',
    `अब उही visitor flow तीन सय नब्बे pixel चौडाइको mobile viewport मा हेरिन्छ। header compact हुन्छ, language control र menu screen बाहिर जाँदैनन्। नेपाली text ले line-height र spacing बिगार्दैन। home बाट सरकारी project सूची र project detail मा जाने primary actions finger-friendly छन्। project title, ministry, status र repository link सानो screen मा क्रमसँग stack हुन्छन्। GitHub issue list horizontal scroll बिना पढ्न सकिन्छ। issue number र title tap गर्न सकिन्छ, र contributor profile पनि उहीँबाट खुल्छ। desktop का लागि बनाइएको dense admin table mobile मा जबरजस्ती नदेखाउनु frontend strip-down को हिस्सा हो। public flow मा आवश्यक information blocks मात्र छन्। अंग्रेजी र नेपाली बदल्दा navigation item को अर्थ उही रहन्छ र route language prefix मात्र बदलिन्छ। screenshot मात्र होइन, Playwright ले वास्तविक Brave rendering मा viewport, links र headings जाँचेर यी frames लिएको हो। mobile visitor लाई account, OAuth वा hidden menu खोज्न नपरोस् भन्ने यसको मुख्य उद्देश्य हो।`,
  ],
  [
    '10-resilience-close.mp3',
    `अन्त्यमा पूरा validated loop एक पटक संक्षेप गरौँ। पहिलो, visitor डेभनेपालमा account बिना आउँछ र जिम्मेवार मन्त्रालयसहित सार्वजनिक project खोज्छ। दोस्रो, उसले project detail मा समस्या, अपेक्षित outcome, synchronized GitHub issues, open pull request र public contributor activity पढ्छ। तेस्रो, issue को पूरा context DevNepal मा बुझेर canonical GitHub page मा जान्छ र discussion, assignment, commit तथा pull request त्यहीँ गर्छ। चौथो, ministry publisher bilingual project create वा edit गर्छ, वास्तविक public repository जोड्छ र workspace बाट GitHub activity refresh गर्छ। पाँचौँ, नयाँ timestamp र audit record ले refresh कहिले र कसले गर्‍यो भन्ने प्रमाण राख्छ। GitHub अस्थायी रूपमा नचले पनि अन्तिम राम्रो snapshot र source links बाँकी रहन्छन्। यस demo मा super-admin flow आवश्यक छैन, user OAuth आवश्यक छैन र अलग legacy profile आवश्यक छैन। narrow scope ले परीक्षण गर्नुपर्ने surface घटाएको छ, तर देखाइएको प्रत्येक link, form, permission boundary र snapshot वास्तविक Django code र database मा चलेको छ। यही २० minute presentation को मुख्य सन्देश हो: visitor-first discovery, GitHub-first collaboration, र ministry-verifiable public accountability।`,
  ],
];

const outputDirectory = path.resolve('public/voice-long');
await mkdir(outputDirectory, {recursive: true});

const run = (command, args, label) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {stdio: ['ignore', 'inherit', 'inherit']});
    child.once('error', (error) => reject(new Error(`Unable to start ${label}`, {cause: error})));
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${label} failed: ${signal ? `signal ${signal}` : `exit ${code}`}`));
    });
  });

for (const [filename, text] of chapters) {
  const outputPath = path.join(outputDirectory, filename);
  const rawPath = path.join(outputDirectory, `.${filename}.raw.wav`);
  try {
    await run(
      kalaBinary,
      [
        ...(usesUvx ? ['--from', 'kala-tts', 'kala-tts'] : []),
        text,
        '--speaker',
        kalaSpeaker,
        '--speed',
        chapterSpeeds[filename] || kalaSpeed,
        '--out',
        rawPath,
      ],
      `Kala TTS for ${filename}`,
    );
    await run(
      ffmpegBinary,
      [
        '-y',
        '-loglevel',
        'error',
        '-i',
        rawPath,
        '-af',
        'loudnorm=I=-16:TP=-2:LRA=7',
        '-ar',
        '48000',
        '-ac',
        '1',
        outputPath,
      ],
      `audio normalization for ${filename}`,
    );
  } finally {
    try {
      await unlink(rawPath);
    } catch (error) {
      if (error?.code !== 'ENOENT') {
        throw new Error(`Unable to remove temporary narration for ${filename}`, {cause: error});
      }
    }
  }
}

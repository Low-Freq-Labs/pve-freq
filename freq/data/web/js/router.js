(function(global){
  'use strict';

  function create(options){
    options=options||{};
    var doc=options.document||global.document;
    var history=options.history||global.history;
    var location=options.location||global.location;
    var loaders=options.loaders||{};
    var aliases=options.aliases||{};
    var viewIds=options.viewIds||[];
    var viewToNav=options.viewToNav||{};
    var viewTitles=options.viewTitles||{};
    var navTitles=options.navTitles||{};

    function resolve(view){
      view=aliases[String(view||'')]||String(view||'');
      return loaders[view]?view:'home';
    }

    function fromLocation(){
      var path=location.pathname.replace(/^\/dashboard\/?/,'').replace(/^\/+|\/+$/g,'');
      return resolve(path||'home');
    }

    function switchView(requested,skipPush){
      var view=resolve(requested);
      if(options.beforeSwitch)options.beforeSwitch();
      if(options.setCurrentView)options.setCurrentView(view);

      viewIds.forEach(function(id){
        var viewElement=doc.getElementById(id+'-view');
        if(viewElement)viewElement.style.display='none';
      });
      var activeView=doc.getElementById(view+'-view');
      if(activeView)activeView.style.display='block';

      var navGroup=viewToNav[view]||view;
      doc.querySelectorAll('.view-btn').forEach(function(button){button.classList.remove('active-view');});
      var activeButton=doc.querySelector('.view-btn[data-view="'+navGroup+'"]');
      if(activeButton)activeButton.classList.add('active-view');

      var title=doc.getElementById('page-title');
      if(title)title.textContent=navTitles[navGroup]||viewTitles[view]||view;
      var tagline=doc.getElementById('header-tagline');
      if(tagline&&options.tagline)tagline.textContent=options.tagline(navGroup);
      if(options.refreshHeader)options.refreshHeader();

      if(!skipPush){
        try{history.pushState({view:view},'','/dashboard/'+view);}catch(e){}
      }
      var loader=loaders[view]||loaders.home;
      if(options.runLoader)options.runLoader(loader);
      else if(loader)loader();
      return view;
    }

    function replaceCurrent(view){
      view=resolve(view);
      try{history.replaceState({view:view},'',location.href);}catch(e){}
      return view;
    }

    function handlePopState(event){
      return switchView(event&&event.state&&event.state.view?event.state.view:fromLocation(),true);
    }

    return {
      resolve:resolve,
      fromLocation:fromLocation,
      switchView:switchView,
      replaceCurrent:replaceCurrent,
      handlePopState:handlePopState
    };
  }

  global.FreqViewRouter={create:create};
})(window);
